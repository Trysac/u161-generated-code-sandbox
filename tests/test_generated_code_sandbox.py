"""Tests for generated_code_sandbox."""

import os
import subprocess
import sys

import pytest

from generated_code_sandbox import (
    Limits,
    Policy,
    SandboxError,
    Violation,
    check_code,
    run_code,
)


def test_acceptance_sum_range_ok() -> None:
    # 1. run_code('print(sum(range(10)))') returns status 'ok', exit_code 0 and stdout '45\n' (CRLF normalised to LF on every OS)
    res = run_code("print(sum(range(10)))")
    assert res.status == "ok"
    assert res.exit_code == 0
    assert res.stdout == "45\n"
    assert res.violations == ()
    assert not res.truncated


def test_acceptance_check_import_and_rejected() -> None:
    # 2. check_code('import os') returns [Violation('import_not_allowed', 1, 0, 'os')], and run_code('import os', python='/nonexistent/python') returns status 'rejected' with that violation without starting a process or raising
    v = check_code("import os")
    assert v == [Violation("import_not_allowed", 1, 0, "os")]
    res = run_code("import os", python="/nonexistent/python")
    assert res.status == "rejected"
    assert res.exit_code is None
    assert res.violations == (Violation("import_not_allowed", 1, 0, "os"),)


def test_acceptance_check_ast_rules() -> None:
    # 3. check_code('().__class__.__bases__[0].__subclasses__()') contains code 'dunder_attribute', check_code('open("x")') contains 'forbidden_name', and check_code('from math import sqrt\nprint(sqrt(4))') == []
    v1 = check_code("().__class__.__bases__[0].__subclasses__()")
    assert any(x.code == "dunder_attribute" for x in v1)
    v2 = check_code('open("x")')
    assert any(x.code == "forbidden_name" for x in v2)
    v3 = check_code("from math import sqrt\nprint(sqrt(4))")
    assert v3 == []


def test_acceptance_timeout_loop() -> None:
    # 4. run_code('while True:\n    pass', limits=Limits(timeout_s=0.2)) returns status 'timeout' with exit_code None and returns in under 10 s
    start = sys.modules["time"].monotonic()
    res = run_code("while True:\n    pass", limits=Limits(timeout_s=0.2))
    elapsed = sys.modules["time"].monotonic() - start
    assert res.status == "timeout"
    assert res.exit_code is None
    assert elapsed < 10.0


def test_acceptance_output_limit() -> None:
    # 5. run_code("print('x' * 100_000)", limits=Limits(max_output_bytes=65_536)) returns status 'output_limit', truncated True and len(stdout) == 65_536
    res = run_code("print('x' * 100_000)", limits=Limits(max_output_bytes=65_536))
    assert res.status == "output_limit"
    assert res.truncated is True
    assert len(res.stdout) == 65_536


def test_acceptance_raise_value_error() -> None:
    # 6. run_code("raise ValueError('boom')") returns status 'error', exit_code 1 and stderr ending with 'ValueError: boom\n'
    res = run_code("raise ValueError('boom')")
    assert res.status == "error"
    assert res.exit_code == 1
    assert res.stderr.endswith("ValueError: boom\n")


def test_acceptance_env_scrubbed_and_directory_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    # 7. With SECRET_TOKEN='abc' in the parent environment and a policy allowing 'os', a snippet printing os.environ prints no 'SECRET_TOKEN', and the working directory it prints no longer exists after run_code returns
    monkeypatch.setenv("SECRET_TOKEN", "abc")
    snippet = "import os\nprint(os.environ.get('SECRET_TOKEN', 'NONE'))\nprint(os.getcwd())"
    p = Policy(allowed_imports=frozenset(["os"]))
    res = run_code(snippet, policy=p)
    assert res.status == "ok"
    lines = res.stdout.strip().split("\n")
    assert lines[0] == "NONE"
    working_dir = lines[1]
    assert not os.path.exists(working_dir)


def test_acceptance_source_too_large_invalid_limits_and_on_event() -> None:
    # 8. A 100_001-character source raises SandboxError with code 'source_too_large', Limits(timeout_s=0) raises code 'invalid_limits', and on_event receives one payload with keys exactly {'event', 'status', 'exit_code', 'duration_s', 'stdout_bytes', 'stderr_bytes'} containing neither source nor output text
    large_src = "x = 1\n" + " " * 100_000
    with pytest.raises(SandboxError) as exc_large:
        check_code(large_src)
    assert exc_large.value.code == "source_too_large"

    with pytest.raises(SandboxError) as exc_large_run:
        run_code(large_src)
    assert exc_large_run.value.code == "source_too_large"

    with pytest.raises(SandboxError) as exc_limits:
        Limits(timeout_s=0)
    assert exc_limits.value.code == "invalid_limits"

    events: list[dict[str, object]] = []
    res = run_code("print('hello')", on_event=events.append)
    assert res.status == "ok"
    assert len(events) == 1
    assert set(events[0].keys()) == {
        "event",
        "status",
        "exit_code",
        "duration_s",
        "stdout_bytes",
        "stderr_bytes",
    }
    assert events[0]["event"] == "run_complete"
    assert events[0]["status"] == "ok"
    assert events[0]["exit_code"] == 0
    assert isinstance(events[0]["duration_s"], float)
    assert events[0]["stdout_bytes"] == len(b"hello\n")
    assert events[0]["stderr_bytes"] == 0


def test_syntax_error_handling() -> None:
    v = check_code("def broken(")
    assert len(v) == 1
    assert v[0].code == "syntax_error"
    assert v[0].line == 1


def test_dotted_import_policy() -> None:
    # Submodule import
    p = Policy(allowed_imports=frozenset(["math"]))
    v1 = check_code("import math.comb", policy=p)
    assert v1 == []
    v2 = check_code("import os.path", policy=p)
    assert len(v2) == 1
    assert v2[0].code == "import_not_allowed"
    assert v2[0].detail == "os.path"

    v3 = check_code("from urllib.request import urlopen", policy=p)
    assert len(v3) == 1
    assert v3[0].code == "import_not_allowed"
    assert v3[0].detail == "urllib.request"


def test_forbidden_names_detection() -> None:
    v = check_code("eval('1+1'); exec('2+2')")
    codes = [x.code for x in v]
    details = [x.detail for x in v]
    assert codes == ["forbidden_name", "forbidden_name"]
    assert details == ["eval", "exec"]


def test_limits_validation() -> None:
    with pytest.raises(SandboxError) as e1:
        Limits(max_output_bytes=0)
    assert e1.value.code == "invalid_limits"

    with pytest.raises(SandboxError) as e2:
        Limits(memory_bytes=-10)
    assert e2.value.code == "invalid_limits"

    with pytest.raises(SandboxError) as e3:
        Limits(cpu_seconds=0)
    assert e3.value.code == "invalid_limits"

    with pytest.raises(SandboxError) as e4:
        Limits(max_file_bytes=0)
    assert e4.value.code == "invalid_limits"

    with pytest.raises(SandboxError) as e5:
        Limits(max_open_files=0)
    assert e5.value.code == "invalid_limits"

    with pytest.raises(SandboxError) as e6:
        Policy(max_source_chars=0)
    assert e6.value.code == "invalid_limits"


def test_interpreter_not_found() -> None:
    with pytest.raises(SandboxError) as exc:
        run_code("x = 1", python="/path/to/nonexistent/python_xyz_bin")
    assert exc.value.code == "interpreter_not_found"


def test_stdin_passthrough() -> None:
    code = "import sys\nprint('got: ' + sys.stdin.read().strip())"
    res = run_code(code, policy=Policy(allowed_imports=frozenset(["sys"])), stdin="input_data")
    assert res.status == "ok"
    assert res.stdout == "got: input_data\n"


def test_output_limit_stderr() -> None:
    code = "import sys\nsys.stderr.write('e' * 10_000)"
    p = Policy(allowed_imports=frozenset(["sys"]))
    res = run_code(code, policy=p, limits=Limits(max_output_bytes=2000))
    assert res.status == "output_limit"
    assert res.truncated is True
    assert len(res.stderr) == 2000


def test_on_event_on_rejection() -> None:
    events: list[dict[str, object]] = []
    res = run_code("import os", on_event=events.append)
    assert res.status == "rejected"
    assert len(events) == 1
    assert events[0]["status"] == "rejected"
    assert events[0]["exit_code"] is None


def test_posix_limits_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    from generated_code_sandbox import _determine_applicable_limits, _setup_posix_limits

    limits = Limits()
    # Should run without error on any OS
    applicable = _determine_applicable_limits(limits)
    assert isinstance(applicable, tuple)
    setup = _setup_posix_limits(limits)
    assert isinstance(setup, list)

    # Test simulated resource module behavior for coverage across platforms
    class MockResource:
        RLIMIT_CPU = 1
        RLIMIT_AS = 2
        RLIMIT_FSIZE = 3
        RLIMIT_NOFILE = 4

        @staticmethod
        def setrlimit(res: int, val: tuple[int, int]) -> None:
            pass

        @staticmethod
        def getrlimit(res: int) -> tuple[int, int]:
            return (10, 20)

    monkeypatch.setattr("generated_code_sandbox.resource", MockResource)

    # _determine_applicable_limits checks resource and os.name == 'nt'
    if os.name != "nt":
        app = _determine_applicable_limits(limits)
        assert app == ("cpu", "memory", "file_size", "open_files")

    st = _setup_posix_limits(limits)
    assert st == ["cpu", "memory", "file_size", "open_files"]

    # Test error handling in setrlimit
    class FailingResource(MockResource):
        @staticmethod
        def setrlimit(res: int, val: tuple[int, int]) -> None:
            raise OSError("simulated")

    monkeypatch.setattr("generated_code_sandbox.resource", FailingResource)
    assert _setup_posix_limits(limits) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process execution flow test")
def test_posix_execution_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    # Test posix branch in run_code
    called_preexec = False

    class FakeProc:
        pid = 12345
        stdin = None
        stdout = None
        stderr = None

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProc:
        nonlocal called_preexec
        assert kwargs.get("start_new_session") is True
        fn = kwargs.get("preexec_fn")
        if callable(fn):
            fn()
            called_preexec = True
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    res = run_code("x = 1")
    assert res.status == "ok"
    assert called_preexec


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process kill test")
def test_kill_process_tree_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    killed_pgid = []

    monkeypatch.setattr("os.getpgid", lambda pid: 999)
    import signal

    monkeypatch.setattr("os.killpg", lambda pgid, sig: killed_pgid.append((pgid, sig)))

    class HangingProc:
        pid = 888
        stdin = None
        stdout = None
        stderr = None
        calls = 0

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(cmd="fake", timeout=0.1)
            return -9

        def kill(self) -> None:
            pass

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: HangingProc())
    res = run_code("x = 1", limits=Limits(timeout_s=0.1))
    assert res.status == "timeout"
    assert (999, signal.SIGKILL) in killed_pgid


def test_custom_clock() -> None:
    cur = 100.0

    def fake_clock() -> float:
        nonlocal cur
        cur += 0.5
        return cur

    res = run_code("x = 1", clock=fake_clock)
    assert res.duration_s >= 0.5


def test_import_from_relative() -> None:
    # from . import foo
    v = check_code("from . import something")
    assert len(v) == 1
    assert v[0].code == "import_not_allowed"
    assert v[0].detail == "."
