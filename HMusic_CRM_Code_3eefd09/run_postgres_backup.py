"""Bound the complete backup, including hashing, SDK retries and uploads."""
import os
from pathlib import Path
import signal
import subprocess
import sys

MAX_RUNTIME_SECONDS = 3600
TERMINATION_GRACE_SECONDS = 10


def run_bounded(command, *, timeout=MAX_RUNTIME_SECONDS,
                grace=TERMINATION_GRACE_SECONDS):
    # A new process group includes pg_dump/pg_restore descendants. Inherited
    # environment stays private; never print command arguments or credentials.
    child = subprocess.Popen(command, start_new_session=True)
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Always kill surviving descendants even if the group leader exits.
        try:
            child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        child.wait()
        print("PostgreSQL backup failed: whole_job_timeout", file=sys.stderr)
        return 124


def main():
    try:
        return run_bounded([sys.executable, str(Path(__file__).with_name("postgres_backup.py"))])
    except Exception:
        print("PostgreSQL backup failed: supervisor_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
