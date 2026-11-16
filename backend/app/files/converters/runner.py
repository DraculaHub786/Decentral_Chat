"""Async subprocess runner: timeouts, process-group kill, injected exec (§3.3).

Every engine goes through this module so that no engine can hang the API
process, leak orphaned children, or report success on a dead process.
"""
import asyncio
import logging
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Exit code we synthesise when we had to kill a process.
EXIT_TIMEOUT = -9

_STDERR_TAIL = 4000


class RunnerError(Exception):
    """Raised when a command cannot be executed at all."""


class CommandFailed(Exception):
    """Raised when a command runs but exits non-zero or times out."""

    def __init__(self, message: str, exit_code: int, stderr: str):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the whole process group so orphaned children (soffice.bin) die too."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
    except Exception as err:  # pragma: no cover - best effort cleanup
        logger.warning("Could not kill process group for pid %s: %s", proc.pid, err)
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def _popen_kwargs(env: Optional[dict], cwd: Optional[Path]) -> dict:
    """Process-group isolation so timeouts can kill the whole tree."""
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "env": env,
        "cwd": str(cwd) if cwd else None,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:  # pragma: no cover - Windows
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return kwargs


async def run(
    command: Sequence[str],
    timeout: int = 300,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    on_stdout: Optional[Callable[[str], None]] = None,
    on_stderr_line: Optional[Callable[[str], None]] = None,
) -> CommandResult:
    """Run ``command`` with a hard timeout and full-tree cleanup.

    ``on_stderr_line`` opts into live streaming of stderr. FFmpeg writes its
    progress there, and ``communicate()`` hides it until the process exits -
    which is why job progress used to jump from 0 straight to 100. Streaming
    costs one reader task, so it only starts when a callback is supplied; the
    default path keeps the cheaper single ``communicate()`` call.
    """
    if not command:
        raise RunnerError("Empty command")

    merged_env = None
    if env:
        merged_env = {**os.environ, **env}

    try:
        proc = subprocess.Popen(list(command), **_popen_kwargs(merged_env, cwd))
    except FileNotFoundError as err:
        raise RunnerError(f"Executable not found: {command[0]}") from err
    except OSError as err:
        raise RunnerError(f"Could not start {command[0]}: {err}") from err

    try:
        if on_stderr_line is not None:
            stdout_b, stderr_b = await _drain_streaming(
                proc, timeout, command[0], on_stderr_line, on_stdout)
        else:
            stdout_b, stderr_b = await asyncio.wait_for(
                asyncio.to_thread(proc.communicate), timeout=timeout
            )
    except asyncio.TimeoutError:
        _kill_process_group(proc)
        raise CommandFailed(
            f"Command timed out after {timeout}s: {command[0]}",
            EXIT_TIMEOUT,
            f"Timed out after {timeout}s",
        )

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")

    if on_stderr_line is None and on_stdout and stdout:
        for line in stdout.splitlines():
            on_stdout(line)

    return CommandResult(exit_code=proc.returncode, stdout=stdout, stderr=stderr)


async def _drain_streaming(proc, timeout: int, name: str, on_stderr_line, on_stdout):
    """Read both pipes line by line so progress callbacks fire live.

    A callback runs on the event loop and must only record state - never block.
    """

    async def drain(stream, sink: list, callback):
        while True:
            raw = await asyncio.to_thread(stream.readline)
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace")
            sink.append(text)
            if callback:
                line = text.strip()
                if line:
                    try:
                        callback(line)
                    except Exception:  # a broken callback must not kill the job
                        logger.exception("Progress callback raised")

    stdout_lines: list = []
    stderr_lines: list = []
    await asyncio.wait_for(
        asyncio.gather(
            drain(proc.stdout, stdout_lines, on_stdout),
            drain(proc.stderr, stderr_lines, on_stderr_line),
            asyncio.to_thread(proc.wait),
        ),
        timeout=timeout,
    )
    return "".join(stdout_lines).encode(), "".join(stderr_lines).encode()


async def run_checked(
    command: Sequence[str],
    timeout: int = 300,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    on_stdout: Optional[Callable[[str], None]] = None,
    on_stderr_line: Optional[Callable[[str], None]] = None,
) -> CommandResult:
    """Like :func:`run` but raises :class:`CommandFailed` on a non-zero exit."""
    result = await run(command, timeout=timeout, cwd=cwd, env=env,
                       on_stdout=on_stdout, on_stderr_line=on_stderr_line)
    if not result.ok:
        tail = (result.stderr or result.stdout or "").strip()[-_STDERR_TAIL:]
        raise CommandFailed(
            f"Command failed (exit {result.exit_code}): {command[0]}",
            result.exit_code,
            tail,
        )
    return result


def build_command(*parts: Optional[str]) -> List[str]:
    """Join command fragments, dropping ``None``/empty entries."""
    return [str(part) for part in parts if part not in (None, "")]
