"""Shared engine contract: every engine returns real output paths (§3.3)."""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .. import settings
from ..runner import CommandFailed, RunnerError
from ..verify import VerifyError

logger = logging.getLogger(__name__)


class EngineUnavailable(Exception):
    """The engine binary or Python dependency is missing on this host."""


class EngineFailed(Exception):
    """The engine ran but could not produce a valid result."""


@dataclass
class EngineOutput:
    """A result may be one file or several (PDF -> one PNG per page)."""

    files: List[Path] = field(default_factory=list)
    engine: str = ""
    metrics: Dict[str, object] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def primary(self) -> Path:
        if not self.files:
            raise EngineFailed("Engine produced no output files")
        return self.files[0]

    def is_multi_file(self) -> bool:
        return len(self.files) > 1


class BaseEngine:
    """Base class. Subclasses declare ``binaries`` and implement ``run``."""

    name = "base"
    binaries: tuple = ()
    modules: tuple = ()

    @property
    def binary(self) -> Optional[str]:
        return settings.which(*self.binaries) if self.binaries else None

    @staticmethod
    def _module_present(module: str) -> bool:
        import importlib.util
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    @property
    def available(self) -> bool:
        """Binaries probed on PATH; library engines probed by import."""
        if self.binaries:
            return self.binary is not None
        if self.modules:
            return all(self._module_present(m) for m in self.modules)
        return True

    def require(self) -> str:
        """Return the executable path or raise EngineUnavailable."""
        if not self.available:
            needs = ", ".join(self.binaries) or "python dependency"
            raise EngineUnavailable(f"{self.name} is unavailable (needs {needs})")
        return self.binary or self.name

    def timeout(self) -> int:
        return settings.CONVERTER_TIMEOUT_SECONDS

    async def run(self, source, target_ext, dest, options):  # pragma: no cover
        raise NotImplementedError

    async def convert(self, source, target_ext, dest, options=None):
        """Run the engine, normalising failures into EngineFailed."""
        try:
            output = await self.run(source, target_ext, dest, options or {})
        except (EngineUnavailable, EngineFailed):
            raise
        except CommandFailed as err:
            lines = (err.stderr or "").strip().splitlines()
            tail = lines[-1] if lines else str(err)
            raise EngineFailed(f"{self.name} failed: {tail}") from err
        except RunnerError as err:
            raise EngineUnavailable(str(err)) from err
        except VerifyError as err:
            raise EngineFailed(f"{self.name} produced unusable output: {err}") from err

        if not output.files:
            raise EngineFailed(f"{self.name} reported success but wrote no files")
        for produced in output.files:
            if not produced.exists():
                raise EngineFailed(f"{self.name} lost {produced.name}")
        if not output.engine:
            output.engine = self.name
        return output


def unique_path(directory, stem, ext):
    """Return a non-colliding output path inside ``directory``."""
    ext = ext.lstrip(".")
    candidate = Path(directory) / f"{stem}.{ext}"
    index = 1
    while candidate.exists():
        candidate = Path(directory) / f"{stem}-{index}.{ext}"
        index += 1
    return candidate
