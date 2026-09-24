"""Потокобезопасное состояние одной длительной операции."""

from dataclasses import dataclass, replace
from threading import Lock, Thread
import time
from typing import Any, Callable


ACTIVE_STATUSES = frozenset({"preparing", "downloading", "filtering"})


@dataclass(frozen=True)
class OperationSnapshot:
    status: str = "idle"
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bytes_per_second: float = 0.0
    checked: int = 0
    matched: int = 0
    error: str | None = None
    result: Any = None

    @property
    def active(self):
        return self.status in ACTIVE_STATUSES

    @property
    def percent(self):
        if self.total_bytes is None or self.total_bytes <= 0:
            return None
        return min(100.0, self.downloaded_bytes * 100.0 / self.total_bytes)


class OperationState:
    """Состояние, которое worker обновляет, а UI читает снимками."""

    def __init__(self, clock=time.monotonic, speed_interval=0.5):
        self._clock = clock
        self._speed_interval = speed_interval
        self._lock = Lock()
        self._snapshot = OperationSnapshot()
        self._started_at = None
        self._sample_at = None
        self._sample_bytes = 0
        self._history = ["idle"]

    def snapshot(self):
        with self._lock:
            return replace(self._snapshot)

    def history(self):
        with self._lock:
            return tuple(self._history)

    def prepare(self):
        with self._lock:
            if self._snapshot.active:
                return False
            self._snapshot = OperationSnapshot(status="preparing")
            self._started_at = None
            self._sample_at = None
            self._sample_bytes = 0
            self._history = ["idle", "preparing"]
            return True

    def begin_download(self, total_bytes=None):
        total = total_bytes if isinstance(total_bytes, int) and total_bytes > 0 else None
        now = self._clock()
        with self._lock:
            self._transition("downloading")
            self._snapshot = replace(
                self._snapshot, total_bytes=total, downloaded_bytes=0,
                speed_bytes_per_second=0.0,
            )
            self._started_at = self._sample_at = now
            self._sample_bytes = 0

    def add_downloaded(self, byte_count):
        if byte_count <= 0:
            return
        now = self._clock()
        with self._lock:
            downloaded = self._snapshot.downloaded_bytes + int(byte_count)
            speed = self._snapshot.speed_bytes_per_second
            elapsed = now - self._sample_at
            if elapsed >= self._speed_interval and elapsed > 0:
                speed = (downloaded - self._sample_bytes) / elapsed
                self._sample_at = now
                self._sample_bytes = downloaded
            self._snapshot = replace(
                self._snapshot, downloaded_bytes=downloaded,
                speed_bytes_per_second=max(0.0, speed),
            )

    def begin_filtering(self):
        now = self._clock()
        with self._lock:
            downloaded = self._snapshot.downloaded_bytes
            total = self._snapshot.total_bytes
            if self._snapshot.status == "downloading" and total is not None:
                downloaded = max(downloaded, total)
            speed = self._snapshot.speed_bytes_per_second
            if self._started_at is not None and now > self._started_at:
                speed = downloaded / (now - self._started_at)
            self._transition("filtering")
            self._snapshot = replace(
                self._snapshot, downloaded_bytes=downloaded,
                speed_bytes_per_second=max(0.0, speed),
            )

    def update_filtering(self, checked, matched):
        with self._lock:
            self._snapshot = replace(
                self._snapshot, checked=max(self._snapshot.checked, int(checked)),
                matched=max(self._snapshot.matched, int(matched)),
            )

    def complete(self, result):
        with self._lock:
            self._transition("completed")
            self._snapshot = replace(self._snapshot, result=result, error=None)

    def fail(self, error):
        with self._lock:
            self._transition("failed")
            self._snapshot = replace(
                self._snapshot,
                error=f"{type(error).__name__}: {error}",
                result=None,
            )

    def _transition(self, status):
        if self._snapshot.status != status:
            self._snapshot = replace(self._snapshot, status=status)
            self._history.append(status)


class OperationController:
    """Запускает не более одного worker и переживает rerun Streamlit."""

    def __init__(self, state=None):
        self.state = state or OperationState()
        self._start_lock = Lock()
        self._thread = None

    def snapshot(self):
        return self.state.snapshot()

    def start(self, operation: Callable[[OperationState], Any]):
        with self._start_lock:
            if self.state.snapshot().active:
                return False
            if self._thread is not None and self._thread.is_alive():
                return False
            if not self.state.prepare():
                return False
            self._thread = Thread(
                target=self._run, args=(operation,), daemon=True,
                name="adfox-log-operation",
            )
            self._thread.start()
            return True

    def _run(self, operation):
        try:
            result = operation(self.state)
            self.state.complete(result)
        except Exception as error:
            self.state.fail(error)

    def wait(self, timeout=None):
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
