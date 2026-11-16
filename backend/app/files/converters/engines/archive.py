"""Archive engine (plan Phase 6): safe packing and unpacking.

Archives were removed in Phase 0 (D-02) because the UI advertised ZIP/TAR/GZ/7Z
without any implementation. They come back here as a controlled feature.

Packing is cheap. *Unpacking* is the dangerous half: a 50 MB archive can
decompress to terabytes, and entry names are attacker-controlled. So every
member is validated before a byte is written - traversal, absolute paths,
member count, expanded size and compression ratio are all checked.
"""
import logging
import os
import tarfile
import tempfile
import zipfile
from pathlib import Path

from .base import BaseEngine, EngineFailed, EngineOutput

logger = logging.getLogger(__name__)

# Hard ceilings for extraction.
MAX_MEMBERS = 200
MAX_MEMBER_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


class ArchiveEngine(BaseEngine):
    """Create or repack zip/tar. Python stdlib only, so always available."""

    name = "archive"
    binaries = ()
    modules = ("zipfile", "tarfile")

    async def run(self, source: Path, target_ext: str, dest: Path, options):
        target_ext = (target_ext or "").lower().lstrip(".")
        source_ext = source.suffix.lower().lstrip(".")
        if target_ext not in ("zip", "tar"):
            raise EngineFailed("the archive engine writes zip and tar only")

        # An archive source means repack: unpack safely, then pack the members.
        if source_ext in ("zip", "tar"):
            members = self._read_members(source)
            return self._pack_members(members, target_ext, dest, source.stem)

        # Anything else is packed alongside its sibling uploads.
        return self._pack_directory(source, target_ext, dest)

    # -- packing -----------------------------------------------------------

    def _pack_directory(self, source: Path, target_ext: str, dest: Path) -> EngineOutput:
        """Pack every file staged in the job's input directory."""
        members = []
        for sibling in sorted(source.parent.iterdir()):
            if sibling.is_file():
                members.append((sibling.name, sibling.read_bytes()))
        if not members:
            raise EngineFailed("nothing to archive")
        return self._pack_members(members, target_ext, dest, source.stem or "archive")

    def _pack_members(self, members, target_ext: str, dest: Path, stem: str) -> EngineOutput:
        output = dest if dest.suffix.lower().lstrip(".") == target_ext else (
            dest.with_name("%s.%s" % (stem or "archive", target_ext))
        )
        output.parent.mkdir(parents=True, exist_ok=True)

        blobs = [(name, payload) for name, payload in members if name]
        if not blobs:
            raise EngineFailed("nothing to archive")

        if target_ext == "zip":
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
                for name, payload in blobs:
                    bundle.writestr(name, payload)
        else:
            with tarfile.open(output, "w") as bundle:
                for name, payload in blobs:
                    info = tarfile.TarInfo(name=name)
                    info.size = len(payload)
                    bundle.addfile(info, _BytesReader(payload))

        logger.info("archive: packed %d file(s) into %s", len(blobs), output.name)
        return EngineOutput(
            files=[output],
            engine=self.name,
            metrics={"members": len(blobs), "bytes": output.stat().st_size},
            warnings=["Archives are not encrypted until you send them."],
        )

    # -- extraction --------------------------------------------------------

    def _read_members(self, source: Path):
        """Return ``[(safe_name, bytes)]`` or raise if the archive is hostile.

        Everything is read here, while the archive handle is open. A previous
        version returned lazy readers and then closed the file, so every read
        failed; this builds the payloads up front instead.
        """
        source_ext = source.suffix.lower().lstrip(".")
        try:
            if source_ext == "zip":
                raw = self._read_zip(source)
            elif source_ext == "tar":
                raw = self._read_tar(source)
            else:
                raise EngineFailed("cannot read .%s archives" % source_ext)
        except (zipfile.BadZipFile, tarfile.TarError) as err:
            raise EngineFailed("not a valid %s archive: %s" % (source_ext, err)) from err

        if not raw:
            raise EngineFailed("archive is empty")

        members = []
        total = 0
        for name, payload in raw:
            safe_name = self._safe_member_name(name)
            if safe_name is None:
                logger.warning("archive: refused unsafe member %r", name)
                continue
            total += len(payload)
            if total > MAX_TOTAL_BYTES:
                raise EngineFailed("archive expands past the safety limit")
            members.append((safe_name, payload))

        if not members:
            raise EngineFailed("archive contained no usable files")
        return members

    def _read_zip(self, source: Path):
        raw = []
        with zipfile.ZipFile(source) as bundle:
            infos = [i for i in bundle.infolist() if not i.is_dir()]
            if len(infos) > MAX_MEMBERS:
                raise EngineFailed("archive has too many members")
            for info in infos:
                if info.file_size > MAX_MEMBER_BYTES:
                    raise EngineFailed("archive member is too large")
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > MAX_COMPRESSION_RATIO:
                    raise EngineFailed("archive looks like a decompression bomb")
                raw.append((info.filename, bundle.read(info)))
        return raw

    def _read_tar(self, source: Path):
        raw = []
        with tarfile.open(source) as bundle:
            members = [m for m in bundle.getmembers() if m.isfile()]
            if len(members) > MAX_MEMBERS:
                raise EngineFailed("archive has too many members")
            for member in members:
                if member.size > MAX_MEMBER_BYTES:
                    raise EngineFailed("archive member is too large")
                handle = bundle.extractfile(member)
                if handle is None:
                    continue
                raw.append((member.name, handle.read()))
        return raw

    @staticmethod
    def _safe_member_name(name: str):
        """Reject traversal and absolute paths; flatten to a bare filename.

        Flattening is deliberate: nested trees are the main way a hostile
        archive writes outside the job's output directory.
        """
        if not name:
            return None
        cleaned = name.replace("\\", "/").strip()
        if cleaned.startswith("/") or ".." in cleaned.split("/"):
            return None
        base = os.path.basename(cleaned)
        if not base or base in (".", "..") or ":" in base:
            return None
        return base


class _BytesReader:
    """Minimal file-like reader so tarfile can pack from memory."""

    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0

    def read(self, size: int = -1):
        if size is None or size < 0:
            chunk = self._data[self._offset:]
            self._offset = len(self._data)
            return chunk
        chunk = self._data[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk
