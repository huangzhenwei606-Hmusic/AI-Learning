import contextlib
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest

from run_postgres_backup import run_bounded, MAX_RUNTIME_SECONDS


class SupervisorTests(unittest.TestCase):
    def test_success_and_failure_exit_status(self):
        self.assertEqual(run_bounded([sys.executable, "-c", "pass"], timeout=2), 0)
        self.assertEqual(run_bounded([sys.executable, "-c", "raise SystemExit(7)"], timeout=2), 7)

    def test_timeout_kills_term_resistant_process(self):
        errors = io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stderr(errors):
            code = run_bounded([sys.executable, "-c",
                "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"],
                timeout=.3, grace=.1)
        self.assertEqual(code, 124)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(errors.getvalue(), "PostgreSQL backup failed: whole_job_timeout\n")

    def test_timeout_stops_descendants_when_leader_exits(self):
        with tempfile.TemporaryDirectory() as folder:
            heartbeat = Path(folder) / "heartbeat"
            descendant = ("import signal,time,pathlib; "
                "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                f"p=pathlib.Path({str(heartbeat)!r}); "
                "\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.02)")
            leader = ("import subprocess,sys,time; "
                      f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(30)")
            with contextlib.redirect_stderr(io.StringIO()):
                code = run_bounded([sys.executable, "-c", leader], timeout=.5, grace=.1)
            self.assertEqual(code, 124)
            self.assertTrue(heartbeat.exists())
            time.sleep(.1)
            before = heartbeat.read_text()
            time.sleep(.15)
            self.assertEqual(heartbeat.read_text(), before)

    def test_production_limit_is_fixed(self):
        self.assertEqual(MAX_RUNTIME_SECONDS, 3600)


if __name__ == "__main__":
    unittest.main()
