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
