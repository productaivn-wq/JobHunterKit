"""
process_lock.py — Single Instance Lock & PID Liveness Engine for JobHunterKit

Delegates to global harness lib.shared.process_lock if available, with local fallback.
Includes TTL-based stale lock detection (WI-PREV-01) and crash-safe cleanup hooks (WI-PREV-03).
"""

import sys
from pathlib import Path

# Try importing from global harness (29_DARWIN)
_harness_root = Path(__file__).resolve().parent.parent.parent.parent / "29_DARWIN"
if _harness_root.exists() and str(_harness_root) not in sys.path:
    sys.path.insert(0, str(_harness_root))

try:
    from lib.shared.process_lock import SingleInstanceLock, is_pid_alive
except ImportError:
    import atexit
    import ctypes
    import json
    import os
    import signal
    import time

    def is_pid_alive(pid: int) -> bool:
        """Verifies if the specified process ID is actively executing on the OS."""
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x0010
                PROCESS_QUERY_INFORMATION = 0x0400
                handle = kernel32.OpenProcess(
                    PROCESS_QUERY_INFORMATION | SYNCHRONIZE, False, pid
                )
                if not handle:
                    return False
                try:
                    exit_code = ctypes.c_ulong()
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        STILL_ACTIVE = 259
                        return exit_code.value == STILL_ACTIVE
                    return False
                finally:
                    kernel32.CloseHandle(handle)
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    # Maximum lock age in seconds before it's considered stale, even if the
    # owning process is still alive (covers deadlocked-but-alive scenarios).
    LOCK_TTL_SECONDS = 1800  # 30 minutes

    # Global registry of active locks for atexit/signal cleanup
    _active_locks: list = []

    def _emergency_lock_cleanup() -> None:
        """atexit hook: remove all lock files owned by this process."""
        pid = os.getpid()
        for lock in _active_locks:
            try:
                if lock.acquired and lock.lock_file.exists():
                    content = lock.lock_file.read_text().strip()
                    data = json.loads(content)
                    if data.get("pid") == pid:
                        lock.lock_file.unlink(missing_ok=True)
                        print(
                            f"[PROCESS LOCK] Emergency cleanup: released {lock.flow_name} lock.",
                            flush=True,
                        )
            except Exception:
                # Best-effort cleanup — don't raise during interpreter shutdown
                try:
                    lock.lock_file.unlink(missing_ok=True)
                except Exception:
                    pass

    atexit.register(_emergency_lock_cleanup)

    def _signal_handler(signum, frame) -> None:
        """SIGTERM/SIGINT hook: clean up locks before exit."""
        _emergency_lock_cleanup()
        sys.exit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except (OSError, ValueError):
        pass  # May fail if not on main thread

    class SingleInstanceLock:
        """Single-instance process locking mechanism with PID verification and stale TTL handling."""

        def __init__(
            self,
            flow_name: str,
            lock_dir: str | None = None,
            ttl_seconds: int = LOCK_TTL_SECONDS,
        ) -> None:
            """Initializes lock context for a given pipeline flow name."""
            self.flow_name = flow_name
            self.ttl_seconds = ttl_seconds
            if lock_dir is None:
                lock_dir_path = Path(__file__).parent.parent
            else:
                lock_dir_path = Path(lock_dir)
            self.lock_file = lock_dir_path / f".{flow_name}.lock"
            self.acquired = False

        def acquire(self) -> bool:
            """Attempts to atomically acquire process lock file, purging stale or dead owner locks."""
            pid = os.getpid()
            lock_data = json.dumps({"pid": pid, "acquired_at": time.time()})

            for _attempt in range(2):
                try:
                    # Atomic creation: fails if file already exists
                    fd = os.open(
                        str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                    )
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(lock_data)
                    self.acquired = True
                    _active_locks.append(self)
                    return True
                except FileExistsError:
                    # File exists; inspect owner
                    try:
                        content = self.lock_file.read_text().strip()
                        try:
                            data = json.loads(content)
                            existing_pid = data["pid"]
                            lock_time = data.get("acquired_at", 0)
                        except (json.JSONDecodeError, KeyError):
                            existing_pid = int(content)
                            lock_time = self.lock_file.stat().st_mtime

                        pid_alive = is_pid_alive(existing_pid)
                        lock_age = time.time() - lock_time
                        ttl_exceeded = lock_age > self.ttl_seconds

                        if pid_alive and not ttl_exceeded:
                            print(
                                f"[PROCESS LOCK] Another instance of {self.flow_name} (PID {existing_pid}, "
                                f"age {lock_age:.0f}s) is currently running. Exiting.",
                                flush=True,
                            )
                            sys.exit(0)
                        elif not pid_alive:
                            print(
                                f"[PROCESS LOCK] Cleaning up stale lock file for {self.flow_name} (dead PID {existing_pid}).",
                                flush=True,
                            )
                            self.lock_file.unlink(missing_ok=True)
                        else:
                            print(
                                f"[PROCESS LOCK] Cleaning up stale lock file for {self.flow_name} "
                                f"(PID {existing_pid} alive but TTL exceeded: {lock_age:.0f}s > {self.ttl_seconds}s).",
                                flush=True,
                            )
                            self.lock_file.unlink(missing_ok=True)
                    except SystemExit:
                        raise
                    except Exception as e:
                        print(
                            f"[PROCESS LOCK] Cleaning invalid lock file for {self.flow_name}: {e}",
                            flush=True,
                        )
                        self.lock_file.unlink(missing_ok=True)

            # Fallback final write if needed
            try:
                self.lock_file.write_text(lock_data)
                self.acquired = True
                _active_locks.append(self)
                return True
            except Exception as e:
                print(
                    f"[PROCESS LOCK] Failed to write lock file {self.lock_file}: {e}",
                    flush=True,
                )
                return False

        def release(self) -> None:
            """Releases acquired lock and removes active registry tracking."""
            if self.acquired and self.lock_file.exists():
                try:
                    content = self.lock_file.read_text().strip()
                    try:
                        data = json.loads(content)
                        owner_pid = data["pid"]
                    except (json.JSONDecodeError, KeyError):
                        owner_pid = int(content)
                    if owner_pid == os.getpid():
                        self.lock_file.unlink(missing_ok=True)
                        print(
                            f"[PROCESS LOCK] Released lock for {self.flow_name}.",
                            flush=True,
                        )
                except Exception as e:
                    print(f"[PROCESS LOCK] Error releasing lock file: {e}", flush=True)
                finally:
                    if self in _active_locks:
                        _active_locks.remove(self)

        def __enter__(self) -> "SingleInstanceLock":
            """Context manager entry acquiring the lock."""
            self.acquire()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            """Context manager exit releasing the lock."""
            self.release()
