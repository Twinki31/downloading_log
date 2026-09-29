"""Версия пользовательского приложения из единственного файла VERSION."""

from pathlib import Path
import re


SEMANTIC_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def read_version(version_file=None):
    """Прочитать и проверить номер версии без выполнения произвольного кода."""
    path = Path(version_file) if version_file else Path(__file__).with_name("VERSION")
    version = path.read_text(encoding="ascii").strip()
    if not SEMANTIC_VERSION.fullmatch(version):
        raise ValueError(f"Некорректная версия в {path}: {version!r}")
    return version


def require_release_tag(tag, version=None):
    """Остановить release-сборку, если тег не равен версии приложения."""
    expected = f"v{version or read_version()}"
    if tag != expected:
        raise ValueError(f"Тег релиза должен быть {expected}, получено: {tag}")
    return expected


APP_VERSION = read_version()
