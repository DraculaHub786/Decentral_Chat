"""LibreOffice engine: named filters and one throwaway profile per job.

Experiment 2 in the plan showed three concurrent `soffice --convert-to pdf`
jobs on the *default* profile silently lost an output: they fight over the
same user installation directory. Every invocation here gets its own
`-env:UserInstallation=file:///...` profile inside the job's temp dir, and the
whole process group is killed on timeout by the runner.
"""
import logging
from pathlib import Path

from .. import runner
from ..verify import verify_output
from .base import BaseEngine, EngineFailed, EngineOutput, unique_path

logger = logging.getLogger(__name__)

# Export filters — named explicitly per format instead of letting the engine guess.
OUTPUT_FILTERS = {
    "pdf": {
        "document": "writer_pdf_Export",
        "slides": "impress_pdf_Export",
        "sheet": "calc_pdf_Export",
    },
    "docx": {"document": "MS Word 2007 XML", "slides": "MS Word 2007 XML"},
    "odt": {"document": "writer8"},
    "rtf": {"document": "Rich Text Format"},
    "pptx": {"slides": "Impress MS PowerPoint 2007 XML"},
    "odp": {"slides": "impress8"},
    "xlsx": {"sheet": "Calc MS Excel 2007 XML"},
    "ods": {"sheet": "calc8"},
    "csv": {"sheet": "Text - txt - csv (StarCalc):44,34,76,1"},
    "txt": {"document": "Text"},
    "html": {"document": "HTML (StarWriter)"},
}

FAMILY_BY_SOURCE = {
    "pptx": "slides", "ppt": "slides", "odp": "slides",
    "xlsx": "sheet", "xls": "sheet", "ods": "sheet", "csv": "sheet",
}


class LibreOfficeEngine(BaseEngine):
    """Office -> PDF and office -> office, through a private soffice profile."""

    name = "libreoffice"
    binaries = ("soffice", "libreoffice")

    async def run(self, source: Path, target_ext: str, dest: Path, options):
        binary = self.require()
        target_ext = target_ext.lower().lstrip(".")
        source_ext = source.suffix.lower().lstrip(".")
        family = FAMILY_BY_SOURCE.get(source_ext, "document")
        work_dir = dest.parent

        # The profile must not live in the output directory: _prune_scratch
        # keeps everything under out/, so a profile written there survived as
        # a lo-profile tree beside every result file. Use the scratch dir.
        scratch = work_dir.parent / "tmp"
        if not scratch.is_dir():
            scratch = work_dir.parent
        profile_dir = scratch / "lo-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        profile_uri = profile_dir.resolve().as_uri()

        convert_to = target_ext
        filters = OUTPUT_FILTERS.get(target_ext, {})
        if filters:
            chosen = filters.get(family) or filters.get("document")
            if chosen:
                convert_to = f"{target_ext}:{chosen}"

        command = [
            binary,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--norestore",
            "--invisible",
            "--nolockcheck",
            "--nodefault",
            "--nofirststartwizard",
            "--convert-to",
            convert_to,
            "--outdir",
            str(work_dir),
            str(source),
        ]

        result = await runner.run_checked(command, timeout=self.timeout(), cwd=work_dir)

        produced = work_dir / f"{source.stem}.{target_ext}"
        if not produced.exists():
            candidates = [
                p for p in work_dir.iterdir()
                if p.is_file() and p.suffix.lower().lstrip(".") == target_ext
            ]
            if not candidates:
                raise EngineFailed(
                    f"LibreOffice wrote no .{target_ext} file "
                    f"(filter {convert_to}): {(result.stderr or '').strip()[-300:]}"
                )
            produced = max(candidates, key=lambda p: p.stat().st_size)

        final = produced if produced == dest else unique_path(work_dir, dest.stem, target_ext)
        if produced != final:
            produced.replace(final)

        metrics = verify_output(final, target_ext)
        output = EngineOutput(files=[final], engine=self.name, metrics=metrics)
        if "font" in (result.stderr or "").lower():
            output.warnings.append("Fonts may have been substituted.")
        return output
