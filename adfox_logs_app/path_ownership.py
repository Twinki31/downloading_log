"""Межпоточное и межпроцессное владение итоговыми путями."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import errno
import json
import os
import socket
import time
import uuid


LOCK_SUFFIX = ".adfox.lock"


class PathBusyError(RuntimeError):
    """Итоговый путь уже зарезервирован другой операцией."""


def publish_file(source, destination, *, replace):
    """Атомарно опубликовать готовый файл согласно политике замены.

    При ``replace=False`` итоговое имя создаётся только если оно ещё свободно:
    hard link на POSIX и не заменяющий rename на Windows. Поэтому между
    проверкой и публикацией нет окна для перезаписи. Оба файла всегда находятся
    в одной папке и не пересекают границы файловых систем.
    """
    source = Path(source)
    destination = Path(destination)
    if replace:
        os.replace(source, destination)
        return
    try:
        if os.name == "nt":
            # В Windows os.rename в той же папке атомарен и отказывается
            # заменять существующий destination.
            os.rename(source, destination)
            return
        os.link(source, destination)
    except FileExistsError as error:
        raise FileExistsError(
            f"Файл уже существует и замена не разрешена: {destination}"
        ) from error
    source.unlink()


def _lock_path(path):
    return path.with_name(path.name + LOCK_SUFFIX)


def _canonical(path):
    return Path(path).expanduser().resolve()


def _pid_is_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        if error.errno == errno.ESRCH:
            return False
        return True
    return True


def _try_file_lock(file):
    """Захватить advisory lock без ожидания; вернуть False, если он занят."""
    if os.name == "nt":
        import msvcrt

        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _unlock_file(file):
    if os.name == "nt":
        import msvcrt

        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    try:
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _same_open_file(file, path):
    try:
        opened = os.fstat(file.fileno())
        current = path.stat()
    except OSError:
        return False
    return (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)


def _read_record(file):
    try:
        file.seek(0)
        raw = file.read().decode("utf-8")
        record = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    required = ("owner", "pid", "host", "created", "path")
    if not isinstance(record, dict) or any(key not in record for key in required):
        return None
    return record


@dataclass
class _HeldLock:
    target: Path
    sidecar: Path
    owner: str
    file: object

    def release(self):
        should_remove = False
        try:
            record = _read_record(self.file)
            should_remove = (
                record is not None
                and record.get("owner") == self.owner
                and record.get("path") == str(self.target)
                and _same_open_file(self.file, self.sidecar)
            )
            if should_remove and os.name != "nt":
                self.sidecar.unlink(missing_ok=True)
        finally:
            _unlock_file(self.file)
            self.file.close()
        if should_remove and os.name == "nt":
            # Windows обычно не разрешает удалить открытый файл. После закрытия
            # повторно сверяем уникальный owner и не трогаем заменённый sidecar.
            try:
                record = json.loads(self.sidecar.read_text(encoding="utf-8"))
                if record.get("owner") == self.owner:
                    self.sidecar.unlink(missing_ok=True)
            except (FileNotFoundError, OSError, AttributeError,
                    json.JSONDecodeError, UnicodeDecodeError):
                pass


def _busy_message(target, *, stale=False):
    if stale:
        return (
            f"Найден lock без подтверждаемого владельца для пути {target}. "
            "Безопасно удалить его автоматически нельзя. Закройте другие экземпляры "
            "приложения и удалите sidecar "
            f"{_lock_path(target)} вручную."
        )
    return (
        f"Путь уже используется другой операцией: {target}. "
        "Дождитесь её завершения или выберите другое имя."
    )


def _remove_stale_lock(target, sidecar):
    """Удалить только доказанно не удерживаемый lock.

    Advisory lock защищает проверку inode и удаление от двух одновременных
    восстановителей. Lock живого PID или другого компьютера не удаляется.
    """
    try:
        file = sidecar.open("r+b")
    except FileNotFoundError:
        return True
    try:
        record = _read_record(file)
        if record is None:
            raise PathBusyError(_busy_message(target, stale=True))
        if (
            not isinstance(record.get("owner"), str)
            or not record["owner"]
            or record.get("path") != str(target)
        ):
            raise PathBusyError(_busy_message(target, stale=True))
        same_host = record.get("host") == socket.gethostname()
        stale = same_host and not _pid_is_alive(record.get("pid"))
        if not stale:
            raise PathBusyError(_busy_message(target))
        if not _try_file_lock(file):
            raise PathBusyError(_busy_message(target))
        if not _same_open_file(file, sidecar):
            return True
        if os.name == "nt":
            # Без атомарного unlink открытого файла нельзя исключить гонку двух
            # восстановителей. На Windows оставляем lock для ручной проверки.
            raise PathBusyError(_busy_message(target, stale=True))
        try:
            sidecar.unlink()
        except OSError as error:
            raise PathBusyError(_busy_message(target, stale=True)) from error
        return True
    finally:
        _unlock_file(file)
        file.close()


def _acquire_one(target, owner):
    target.parent.mkdir(parents=True, exist_ok=True)
    sidecar = _lock_path(target)
    record = {
        "owner": owner,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "created": time.time(),
        "path": str(target),
    }
    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")

    while True:
        try:
            descriptor = os.open(sidecar, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            _remove_stale_lock(target, sidecar)
            continue

        file = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            file.write(payload)
            os.fsync(file.fileno())
            if not _try_file_lock(file):
                raise RuntimeError(f"Не удалось зафиксировать собственный lock: {sidecar}")
            return _HeldLock(target, sidecar, owner, file)
        except Exception:
            try:
                if _same_open_file(file, sidecar):
                    sidecar.unlink(missing_ok=True)
            finally:
                _unlock_file(file)
                file.close()
            raise


@contextmanager
def reserve_paths(paths):
    """Зарезервировать уникальные пути в стабильном порядке."""
    targets = sorted({_canonical(path) for path in paths}, key=lambda path: os.path.normcase(str(path)))
    owner = uuid.uuid4().hex
    held = []
    try:
        for target in targets:
            held.append(_acquire_one(target, owner))
        yield owner
    finally:
        for lock in reversed(held):
            lock.release()
