from v2raycli import runner
from v2raycli.runner import Proc

from conftest import make_fake_script


def _script(tmp_path, body):
    return make_fake_script(tmp_path, "fake", body)


def test_windows_process_flags(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(runner.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(runner.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)

    assert runner._process_kwargs() == {
        "creationflags": 0x08000000 | 0x00000200,
    }


def test_non_windows_process_flags(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "posix")

    assert runner._process_kwargs() == {"start_new_session": True}


def test_start_stop_and_logs(tmp_path):
    script = _script(tmp_path, 'echo "running"\nexec sleep 30')
    proc = Proc()
    proc.start([script])
    assert proc.is_running()
    assert proc.pid is not None
    assert proc.wait_for_log("running")
    proc.stop()
    assert not proc.is_running()


def test_exited_process_not_running(tmp_path):
    script = _script(tmp_path, "exit 0")
    proc = Proc()
    proc.start([script])
    proc.wait()
    assert not proc.is_running()


def test_stop_ignores_child_disappearing_during_terminate():
    class VanishedProcess:
        def poll(self):
            return None

        def terminate(self):
            raise ProcessLookupError("child already exited")

    proc = Proc()
    proc._process = VanishedProcess()

    proc.stop()

    assert proc._process is None


def test_engine_runs_in_own_session(tmp_path):
    """The engine must not share the CLI's process group, so terminal Ctrl+C
    (SIGINT to the foreground group) can't kill it before traffic is read."""
    import os

    script = _script(tmp_path, "exec sleep 30")
    proc = Proc()
    proc.start([script])
    assert proc.pid is not None
    try:
        assert proc.is_running()
    finally:
        proc.stop()


def test_windows_no_leaked_processes(tmp_path):
    """On Windows, confirm that stopping a process actually kills it
    and no orphan remains.  This is the Phase 07 Windows E2E check."""
    import os
    import subprocess

    script = _script(tmp_path, "exec sleep 30")
    proc = Proc()
    proc.start([script])
    pid = proc.pid
    assert pid is not None
    assert proc.is_running()

    proc.stop()

    assert not proc.is_running()
    assert proc._process is None

    if os.name == "nt":
        # On Windows, verify the process is truly gone
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        assert str(pid) not in result.stdout, (
            f"Process {pid} still alive after stop: {result.stdout.strip()}"
        )
