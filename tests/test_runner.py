from v2raycli.runner import Proc


def _script(tmp_path, body):
    script = tmp_path / "fake.sh"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(0o755)
    return str(script)


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
    import signal
    import time

    script = _script(tmp_path, "exec sleep 30")
    proc = Proc()
    proc.start([script])
    assert proc.pid is not None
    try:
        # Same PID as the shell would mean no new session was created.
        if os.name == "nt":
            assert proc._process is not None
            assert proc._process.creationflags & 0x00000200  # CREATE_NEW_PROCESS_GROUP
        else:
            with open(f"/proc/{proc.pid}/stat") as fh:
                fields = fh.read().split()
            assert fields[4] == str(proc.pid), "child must be its own session leader"
    finally:
        proc.stop()
