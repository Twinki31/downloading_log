"""Потокобезопасное состояние одной длительной операции."""

from dataclasses import dataclass, replace
import re
from threading import Condition, Lock, Thread
import time
from typing import Any, Callable


ACTIVE_STATUSES = frozenset({
    "preparing", "downloading", "pausing", "paused", "filtering", "cancelling",
})

_SENSITIVE_ERROR_PATTERNS = (
    re.compile(
        r"(?i)(aws_access_key_id|aws_secret_access_key|aws_session_token|"
        r"access[_-]?token|secret[_-]?key|password)\s*([:=])\s*([^\s,;]+)"
    ),
    re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
)


def safe_error_text(error):
    """Вернуть полезное сообщение без распространённых форматов секретов."""
    text = str(error)
    text = _SENSITIVE_ERROR_PATTERNS[0].sub(r"\1\2<скрыто>", text)
    text = _SENSITIVE_ERROR_PATTERNS[1].sub(r"\1<скрыто>@", text)
    text = _SENSITIVE_ERROR_PATTERNS[2].sub("<скрыто>", text)
    return f"{type(error).__name__}: {text}"


class OperationCancelled(Exception):
    """Кооперативная остановка фоновой операции по команде пользователя."""


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
    """Состояние и команды, которыми обмениваются UI и один worker."""

    def __init__(self, clock=time.monotonic, speed_interval=0.5):
        self._clock = clock
        self._speed_interval = speed_interval
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._snapshot = OperationSnapshot()
        self._started_at = None
        self._sample_at = None
        self._sample_bytes = 0
        self._paused_total = 0.0
        self._pause_started_at = None
        self._pause_requested = False
        self._cancel_requested = False
        self._history = ["idle"]

    def snapshot(self):
        with self._lock:
            return replace(self._snapshot)

    def history(self):
        with self._lock:
            return tuple(self._history)

    def prepare(self):
        with self._condition:
            if self._snapshot.active:
                return False
            self._snapshot = OperationSnapshot(status="preparing")
            self._started_at = None
            self._sample_at = None
            self._sample_bytes = 0
            self._paused_total = 0.0
            self._pause_started_at = None
            self._pause_requested = False
            self._cancel_requested = False
            self._history = ["idle", "preparing"]
            return True

    def begin_download(self, total_bytes=None):
        total = total_bytes if isinstance(total_bytes, int) and total_bytes > 0 else None
        now = self._clock()
        with self._condition:
            self._raise_if_cancelled()
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
            self._raise_if_cancelled()
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

    def request_pause(self):
        """Запросить паузу; worker подтвердит её на границе порции."""
        with self._condition:
            if self._snapshot.status not in ("downloading", "pausing"):
                return False
            if not self._pause_requested:
                self._pause_requested = True
                self._transition("pausing")
            return True

    def resume(self):
        """Снять паузу или ещё не исполненный запрос паузы."""
        now = self._clock()
        with self._condition:
            if self._snapshot.status not in ("pausing", "paused"):
                return False
            if self._pause_started_at is not None:
                self._paused_total += max(0.0, now - self._pause_started_at)
                self._pause_started_at = None
            self._pause_requested = False
            self._sample_at = now
            self._sample_bytes = self._snapshot.downloaded_bytes
            self._transition("downloading")
            self._condition.notify_all()
            return True

    def wait_download_permission(self):
        """Остановиться между range-запросами; вернуть True после реальной паузы."""
        paused = False
        with self._condition:
            self._raise_if_cancelled()
            while self._pause_requested:
                if not paused:
                    paused = True
                    self._pause_started_at = self._clock()
                    self._transition("paused")
                self._condition.wait()
                self._raise_if_cancelled()
            return paused

    def check_cancelled(self):
        with self._lock:
            self._raise_if_cancelled()

    def request_cancel(self):
        """Идемпотентно запросить отмену и разбудить worker на паузе."""
        with self._condition:
            if not self._snapshot.active:
                return False
            first_request = not self._cancel_requested
            self._cancel_requested = True
            self._pause_requested = False
            self._transition("cancelling")
            self._condition.notify_all()
            return first_request

    def begin_filtering(self):
        now = self._clock()
        with self._condition:
            self._raise_if_cancelled()
            downloaded = self._snapshot.downloaded_bytes
            total = self._snapshot.total_bytes
            if self._snapshot.status == "downloading" and total is not None:
                downloaded = max(downloaded, total)
            speed = self._snapshot.speed_bytes_per_second
            active_elapsed = None
            if self._started_at is not None:
                active_elapsed = now - self._started_at - self._paused_total
            if active_elapsed is not None and active_elapsed > 0:
                speed = downloaded / active_elapsed
            self._transition("filtering")
            self._snapshot = replace(
                self._snapshot, downloaded_bytes=downloaded,
                speed_bytes_per_second=max(0.0, speed),
            )

    def update_filtering(self, checked, matched):
        with self._lock:
            self._raise_if_cancelled()
            self._snapshot = replace(
                self._snapshot, checked=max(self._snapshot.checked, int(checked)),
                matched=max(self._snapshot.matched, int(matched)),
            )

    def complete(self, result):
        with self._condition:
            self._raise_if_cancelled()
            self._transition("completed")
            self._snapshot = replace(self._snapshot, result=result, error=None)

    def cancelled(self):
        with self._condition:
            self._transition("cancelled")
            self._snapshot = OperationSnapshot(status="cancelled")
            self._condition.notify_all()

    def fail(self, error):
        with self._condition:
            self._transition("failed")
            self._snapshot = replace(
                self._snapshot,
                error=safe_error_text(error),
                result=None,
            )
            self._condition.notify_all()

    def _raise_if_cancelled(self):
        if self._cancel_requested:
            raise OperationCancelled("Операция отменена пользователем")

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

    def pause(self):
        return self.state.request_pause()

    def resume(self):
        return self.state.resume()

    def cancel(self):
        return self.state.request_cancel()

    def _run(self, operation):
        try:
            result = operation(self.state)
            self.state.complete(result)
        except OperationCancelled:
            self.state.cancelled()
        except Exception as error:
            self.state.fail(error)

    def wait(self, timeout=None):
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
