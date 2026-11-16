"""Phase 6: archive packing works, and hostile archives are refused.

Security is the point of this test. Packing is easy; the value of the feature
is that a zip-bomb or a ``../`` member cannot hurt the server.
"""
import asyncio
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.files.converters import routes_table, settings
from app.files.converters import workspace as workspace_mod
from app.files.converters.engines import get_engine
from app.files.converters.engines.base import EngineFailed


def fresh_ws(job_id):
    return workspace_mod.create(job_id)


async def case_pack():
    """png -> zip packs the file."""
    ws = fresh_ws("p6-pack")
    src = ws.input_dir / "pic.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    dest = ws.output_path("pic.zip")

    engine = get_engine("archive")
    assert engine.available, "archive engine should always be available"
    out = await engine.convert(src, "zip", dest)

    assert out.primary.exists(), "no zip produced"
    with zipfile.ZipFile(out.primary) as bundle:
        names = bundle.namelist()
    print("packed:", names)
    assert "pic.png" in names, names
    ws.cleanup()


async def case_zip_to_tar():
    """zip -> tar repacks the contents, not the container."""
    ws = fresh_ws("p6-repack")
    src = ws.input_dir / "bundle.zip"
    with zipfile.ZipFile(src, "w") as bundle:
        bundle.writestr("a.txt", b"alpha")
        bundle.writestr("b.txt", b"beta")

    dest = ws.output_path("bundle.tar")
    out = await get_engine("archive").convert(src, "tar", dest)

    with tarfile.open(out.primary) as bundle:
        names = sorted(m.name for m in bundle.getmembers() if m.isfile())
    print("repacked:", names)
    assert names == ["a.txt", "b.txt"], names
    ws.cleanup()


async def case_traversal():
    """A ../ member must not escape the output directory."""
    ws = fresh_ws("p6-traversal")
    src = ws.input_dir / "evil.zip"
    with zipfile.ZipFile(src, "w") as bundle:
        bundle.writestr("../../escaped.txt", b"pwned")
        bundle.writestr("safe.txt", b"ok")

    dest = ws.output_path("evil.tar")
    out = await get_engine("archive").convert(src, "tar", dest)

    escaped = (ws.output_dir.parent / "escaped.txt").exists()
    assert not escaped, "path traversal escaped the workspace"

    with tarfile.open(out.primary) as bundle:
        names = sorted(m.name for m in bundle.getmembers() if m.isfile())
    print("surviving members:", names)
    assert names == ["safe.txt"], names
    ws.cleanup()


async def case_bomb():
    """A high-ratio member must be rejected, not expanded."""
    ws = fresh_ws("p6-bomb")
    src = ws.input_dir / "bomb.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("bomb.bin", b"\0" * (8 * 1024 * 1024))

    dest = ws.output_path("bomb.tar")
    try:
        await get_engine("archive").convert(src, "tar", dest)
    except EngineFailed as err:
        print("bomb rejected:", err)
    else:
        raise AssertionError("decompression bomb was not rejected")
    finally:
        ws.cleanup()


def case_routes():
    """Registry advertises the archive routes it can actually run."""
    for src, dst in (("png", "zip"), ("pdf", "zip"), ("docx", "tar"),
                     ("zip", "tar"), ("tar", "zip")):
        route = routes_table.lookup(src, dst)
        assert route is not None, "%s->%s not advertised" % (src, dst)
        assert route.available, "%s->%s advertised but unavailable" % (src, dst)
        assert route.available_engine() == "archive", route.engines
    print("routes: png/pdf/docx -> zip|tar, zip<->tar all resolve to archive")


async def main():
    settings.ensure_work_dir()
    case_routes()
    await case_pack()
    await case_zip_to_tar()
    await case_traversal()
    await case_bomb()
    print("PHASE 6 ARCHIVES OK")


asyncio.run(main())
