"""Generic subprocess lifecycle helper (engine cores and VPN clients)."""

from __future__ import annotations

import os
import subprocess
import threading
import time


def _process_kwargs() -> dict:
    """Return platform-specific flags for a long-running child process."""
    if os.name == "nt":
        # No console window for the engine, and keep it out of the
        # console's Ctrl+C group so a Ctrl+C on the CLI doesn't kill the
        # engine before traffic can be recorded.
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    # Own session: terminal Ctrl+C (SIGINT to the foreground group) reaches
    # only the CLI, which then records traffic and stops the engine gracefully
    # instead of the engine dying mid-read.
    return {"start_new_session": True}


class Proc:
    """Manage one long-running child process with log capture."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._logs: list[str] = []
        self.started_at: float | None = None

    def start(self, argv: list[str], env=None) -> None:
        self._process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            **_process_kwargs(),
        )
        self.started_at = time.time()
        self._logs = []
        for pipe in (self._process.stdout, self._process.stderr):
            if pipe is not None:
                threading.Thread(target=self._drain, args=(pipe,), daemon=True).start()

    def _drain(self, pipe) -> None:
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            if text:
                self._logs.append(text)

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def wait(self, timeout: float | None = None) -> int | None:
        if self._process is not None:
            return self._process.wait(timeout=timeout)
        return None

    def logs(self) -> list[str]:
        return list(self._logs)

    def wait_for_log(self, substring: str, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if any(substring in line for line in self._logs):
                return True
            time.sleep(0.05)
        return False

    def stop(self, grace_seconds: float = 2.0) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                # The child may have exited between poll() and terminate().
                return
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    return
                try:
                    process.wait()
                except (OSError, ChildProcessError):
                    pass
            except (OSError, ChildProcessError):
                # Shutdown is best-effort; never let a disappearing child
                # break the caller's disconnect path.
                pass
