"""generated_code_sandbox: Run LLM-generated Python snippets in an isolated sub-interpreter.

Provides AST-level guardrails, execution timeouts, output size caps, environment scrubbing,
and POSIX resource limits via standard library subprocess and resource modules.

Threat model and honest guarantees:
Defended:
- Runaway execution loops (enforced via timeout and process group termination).
- Output floods filling host memory (enforced via capped stream reading and process killing).
- Host environment secret leakage (scrubbed environment, passing only essential OS vars).
- Leftover scratch files in the working directory (isolated temporary directory cleaned in finally).
- Accidental imports and forbidden builtins outside policy.

Not defended:
- Deliberate AST-level escapes (AST inspection is a guardrail, not a secure boundary).
- Host filesystem access allowed to the running user account.
- Direct network access if the host has open network access.
- Grandchild processes on Windows.
- Virtual memory exhaustion on platforms where RLIMIT_AS is unsupported or advisory (e.g. macOS).
For hostile code execution, use containerized isolation, gVisor, MicroVMs, or WASM sandboxes.
"""

from __future__ import annotations

import ast
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, Literal

try:
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

__all__ = [
    "DEFAULT_FORBIDDEN",
    "DEFAULT_IMPORTS",
    "Limits",
    "Policy",
    "RunResult",
    "SandboxError",
    "Violation",
    "__version__",
    "check_code",
    "run_code",
]

__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

DEFAULT_IMPORTS: frozenset[str] = frozenset(
    [
        "math",
        "json",
        "re",
        "itertools",
        "functools",
        "collections",
        "statistics",
        "datetime",
        "decimal",
        "fractions",
        "string",
        "random",
        "textwrap",
        "heapq",
        "bisect",
        "operator",
        "dataclasses",
        "typing",
        "enum",
    ]
)

DEFAULT_FORBIDDEN: frozenset[str] = frozenset(
    [
        "__import__",
        "eval",
        "exec",
        "compile",
        "open",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "breakpoint",
        "input",
        "memoryview",
        "help",
        "exit",
        "quit",
    ]
)

ErrorCode = Literal["source_too_large", "invalid_limits", "interpreter_not_found"]
ViolationCode = Literal["syntax_error", "import_not_allowed", "forbidden_name", "dunder_attribute"]
RunStatus = Literal["ok", "error", "timeout", "output_limit", "rejected"]


class SandboxError(Exception):
    """Base exception raised for sandbox configuration and resource limits errors."""

    def __init__(self, code: ErrorCode, message: str = "") -> None:
        self.code = code
        msg = message or f"Sandbox error: {code}"
        super().__init__(msg)


@dataclass(frozen=True)
class Policy:
    """Policy for static AST-level checks on Python code snippets."""

    allowed_imports: frozenset[str] = DEFAULT_IMPORTS
    forbidden_names: frozenset[str] = DEFAULT_FORBIDDEN
    max_source_chars: int = 100_000

    def __post_init__(self) -> None:
        if self.max_source_chars <= 0:
            raise SandboxError("invalid_limits", "max_source_chars must be greater than zero")


@dataclass(frozen=True)
class Limits:
    """Execution limits applied during subprocess invocation."""

    timeout_s: float = 5.0
    max_output_bytes: int = 65_536
    memory_bytes: int = 268_435_456
    cpu_seconds: int = 5
    max_file_bytes: int = 1_048_576
    max_open_files: int = 64

    def __post_init__(self) -> None:
        fields = [
            ("timeout_s", self.timeout_s),
            ("max_output_bytes", self.max_output_bytes),
            ("memory_bytes", self.memory_bytes),
            ("cpu_seconds", self.cpu_seconds),
            ("max_file_bytes", self.max_file_bytes),
            ("max_open_files", self.max_open_files),
        ]
        for name, val in fields:
            if val <= 0:
                raise SandboxError("invalid_limits", f"{name} must be greater than 0")


@dataclass(frozen=True)
class Violation:
    """A static policy violation or syntax error detected in source code."""

    code: ViolationCode
    line: int
    col: int
    detail: str


@dataclass(frozen=True)
class RunResult:
    """The outcome of executing a code snippet."""

    status: RunStatus
    exit_code: int | None
    stdout: str
    stderr: str
    truncated: bool
    duration_s: float
    violations: tuple[Violation, ...]
    limits_applied: tuple[str, ...]


_DEFAULT_POLICY = Policy()
_DEFAULT_LIMITS = Limits()


def check_code(source: str, policy: Policy = _DEFAULT_POLICY) -> list[Violation]:
    """Statically inspect Python source code against the given policy.

    Checks for syntax errors, disallowed imports, forbidden names, and dunder attribute access.
    Violations are sorted by line, col, code.
    """
    if len(source) > policy.max_source_chars:
        raise SandboxError(
            "source_too_large",
            f"Source length {len(source)} exceeds max_source_chars {policy.max_source_chars}",
        )

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        line = e.lineno if e.lineno is not None else 1
        col = (e.offset - 1) if (e.offset is not None and e.offset > 0) else 0
        detail = e.msg or "invalid syntax"
        return [Violation(code="syntax_error", line=line, col=col, detail=detail)]

    violations: list[Violation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level not in policy.allowed_imports:
                    violations.append(
                        Violation(
                            code="import_not_allowed",
                            line=node.lineno,
                            col=node.col_offset,
                            detail=alias.name,
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            top_level = module_name.split(".")[0] if module_name else ""
            if not top_level or top_level not in policy.allowed_imports:
                detail = module_name if module_name else "."
                violations.append(
                    Violation(
                        code="import_not_allowed",
                        line=node.lineno,
                        col=node.col_offset,
                        detail=detail,
                    )
                )
        elif isinstance(node, ast.Name):
            if node.id in policy.forbidden_names:
                violations.append(
                    Violation(
                        code="forbidden_name",
                        line=node.lineno,
                        col=node.col_offset,
                        detail=node.id,
                    )
                )
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if len(attr) >= 4 and attr.startswith("__") and attr.endswith("__"):
                violations.append(
                    Violation(
                        code="dunder_attribute",
                        line=node.lineno,
                        col=node.col_offset,
                        detail=attr,
                    )
                )

    violations.sort(key=lambda v: (v.line, v.col, v.code))
    return violations


def _setup_posix_limits(limits: Limits) -> list[str]:
    """Applies POSIX resource limits in preexec_fn; returns applied limit names."""
    applied: list[str] = []
    if resource is None:
        return applied

    # CPU seconds
    rlimit_cpu = getattr(resource, "RLIMIT_CPU", None)
    if rlimit_cpu is not None:
        try:
            setrlimit_fn = getattr(resource, "setrlimit", None)
            if setrlimit_fn is not None:
                setrlimit_fn(rlimit_cpu, (int(limits.cpu_seconds), int(limits.cpu_seconds) + 1))
                applied.append("cpu")
        except (ValueError, OSError):
            pass

    # Virtual memory bytes
    rlimit_as = getattr(resource, "RLIMIT_AS", None)
    if rlimit_as is not None:
        try:
            setrlimit_fn = getattr(resource, "setrlimit", None)
            if setrlimit_fn is not None:
                setrlimit_fn(rlimit_as, (int(limits.memory_bytes), int(limits.memory_bytes)))
                applied.append("memory")
        except (ValueError, OSError):
            pass

    # Maximum file size created
    rlimit_fsize = getattr(resource, "RLIMIT_FSIZE", None)
    if rlimit_fsize is not None:
        try:
            setrlimit_fn = getattr(resource, "setrlimit", None)
            if setrlimit_fn is not None:
                setrlimit_fn(rlimit_fsize, (int(limits.max_file_bytes), int(limits.max_file_bytes)))
                applied.append("file_size")
        except (ValueError, OSError):
            pass

    # Maximum number of open file descriptors
    rlimit_nofile = getattr(resource, "RLIMIT_NOFILE", None)
    if rlimit_nofile is not None:
        try:
            getrlimit_fn = getattr(resource, "getrlimit", None)
            setrlimit_fn = getattr(resource, "setrlimit", None)
            if getrlimit_fn is not None and setrlimit_fn is not None:
                _soft, hard = getrlimit_fn(rlimit_nofile)
                limit_val = min(int(limits.max_open_files), hard)
                setrlimit_fn(rlimit_nofile, (limit_val, limit_val))
                applied.append("open_files")
        except (ValueError, OSError):
            pass

    return applied


def _determine_applicable_limits(limits: Limits) -> tuple[str, ...]:
    """Determines which POSIX limits can be applied successfully."""
    if resource is None or os.name == "nt":
        return ()
    applied: list[str] = []
    if hasattr(resource, "RLIMIT_CPU"):
        applied.append("cpu")
    if hasattr(resource, "RLIMIT_AS"):
        applied.append("memory")
    if hasattr(resource, "RLIMIT_FSIZE"):
        applied.append("file_size")
    if hasattr(resource, "RLIMIT_NOFILE"):
        applied.append("open_files")
    return tuple(applied)


def run_code(
    source: str,
    *,
    policy: Policy = _DEFAULT_POLICY,
    limits: Limits = _DEFAULT_LIMITS,
    python: str = sys.executable,
    stdin: str = "",
    clock: Callable[[], float] = time.monotonic,
    on_event: Callable[[dict[str, object]], None] | None = None,
) -> RunResult:
    """Execute a Python code snippet in an isolated sub-interpreter process."""
    if len(source) > policy.max_source_chars:
        raise SandboxError(
            "source_too_large",
            f"Source length {len(source)} exceeds max_source_chars {policy.max_source_chars}",
        )

    violations = check_code(source, policy=policy)
    if violations:
        res = RunResult(
            status="rejected",
            exit_code=None,
            stdout="",
            stderr="",
            truncated=False,
            duration_s=0.0,
            violations=tuple(violations),
            limits_applied=(),
        )
        if on_event is not None:
            on_event(
                {
                    "event": "run_complete",
                    "status": res.status,
                    "exit_code": res.exit_code,
                    "duration_s": res.duration_s,
                    "stdout_bytes": 0,
                    "stderr_bytes": 0,
                }
            )
        return res

    # Prepare execution directory
    temp_dir = tempfile.mkdtemp(prefix="codebox_")
    main_py = os.path.join(temp_dir, "main.py")
    with open(main_py, "w", encoding="utf-8") as f:
        f.write(source)

    # Prepare environment: scrubbed env plus SYSTEMROOT on Windows
    env: dict[str, str] = {}
    if os.name == "nt" and "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

    cmd = [python, "-I", "-B", "-X", "utf8", "main.py"]

    # Subprocess creation flags
    popen_kwargs: dict[str, object] = {
        "cwd": temp_dir,
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
    }

    limits_applied: tuple[str, ...] = ()
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        popen_kwargs["creationflags"] = 0x00000200
    else:
        popen_kwargs["start_new_session"] = True
        limits_applied = _determine_applicable_limits(limits)
        popen_kwargs["preexec_fn"] = lambda: _setup_posix_limits(limits)

    start_time = clock()
    timed_out = False
    output_exceeded = False

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)  # type: ignore[call-overload]
    except FileNotFoundError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise SandboxError(
            "interpreter_not_found", f"Python interpreter not found: {python}"
        ) from exc
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    def kill_process_tree() -> None:
        with contextlib.suppress(Exception):
            if os.name == "nt":
                proc.kill()
            else:
                import signal

                try:
                    getpgid = getattr(os, "getpgid", None)
                    killpg = getattr(os, "killpg", None)
                    sigkill = getattr(signal, "SIGKILL", None)
                    if getpgid is not None and killpg is not None and sigkill is not None:
                        killpg(getpgid(proc.pid), sigkill)
                    else:
                        proc.kill()
                except (OSError, ProcessLookupError):
                    proc.kill()

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_count = 0
    stderr_count = 0
    lock = threading.Lock()

    def read_stream(stream: IO[bytes] | None, is_stdout: bool) -> None:
        nonlocal output_exceeded
        if stream is None:
            return
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            with lock:
                if is_stdout:
                    nonlocal stdout_count
                    needed = limits.max_output_bytes - stdout_count
                    if needed > 0:
                        stdout_chunks.append(chunk[:needed])
                    stdout_count += len(chunk)
                    if stdout_count > limits.max_output_bytes:
                        output_exceeded = True
                        kill_process_tree()
                        break
                else:
                    nonlocal stderr_count
                    needed = limits.max_output_bytes - stderr_count
                    if needed > 0:
                        stderr_chunks.append(chunk[:needed])
                    stderr_count += len(chunk)
                    if stderr_count > limits.max_output_bytes:
                        output_exceeded = True
                        kill_process_tree()
                        break

    try:
        # Write stdin concurrently or directly
        if stdin and proc.stdin is not None:
            with contextlib.suppress(BrokenPipeError, OSError):
                proc.stdin.write(stdin.encode("utf-8"))
                proc.stdin.flush()
        if proc.stdin is not None:
            proc.stdin.close()

        t_out = threading.Thread(target=read_stream, args=(proc.stdout, True), daemon=True)
        t_err = threading.Thread(target=read_stream, args=(proc.stderr, False), daemon=True)
        t_out.start()
        t_err.start()

        try:
            proc.wait(timeout=limits.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_tree()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=1.0)

        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)
    finally:
        # Ensure process is dead and clean temporary directory
        if proc.poll() is None:
            kill_process_tree()
            with contextlib.suppress(Exception):
                proc.wait(timeout=0.5)
        shutil.rmtree(temp_dir, ignore_errors=True)

    duration_s = max(0.0, clock() - start_time)
    raw_stdout = b"".join(stdout_chunks)
    raw_stderr = b"".join(stderr_chunks)

    # Truncate to max_output_bytes exactly
    truncated = False
    if (
        output_exceeded
        or stdout_count > limits.max_output_bytes
        or stderr_count > limits.max_output_bytes
    ):
        truncated = True
        if len(raw_stdout) > limits.max_output_bytes:
            raw_stdout = raw_stdout[: limits.max_output_bytes]
        if len(raw_stderr) > limits.max_output_bytes:
            raw_stderr = raw_stderr[: limits.max_output_bytes]

    out_str = raw_stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    err_str = raw_stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stdout_bytes = len(out_str.encode("utf-8"))
    stderr_bytes = len(err_str.encode("utf-8"))

    if output_exceeded:
        status: RunStatus = "output_limit"
        exit_code: int | None = proc.poll()
    elif timed_out:
        status = "timeout"
        exit_code = None
    else:
        exit_code = proc.poll()
        status = "ok" if exit_code == 0 else "error"

    res = RunResult(
        status=status,
        exit_code=exit_code,
        stdout=out_str,
        stderr=err_str,
        truncated=truncated,
        duration_s=duration_s,
        violations=(),
        limits_applied=limits_applied,
    )

    if on_event is not None:
        on_event(
            {
                "event": "run_complete",
                "status": res.status,
                "exit_code": res.exit_code,
                "duration_s": res.duration_s,
                "stdout_bytes": stdout_bytes,
                "stderr_bytes": stderr_bytes,
            }
        )

    return res
