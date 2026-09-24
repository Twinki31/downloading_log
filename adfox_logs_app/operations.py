"""Оркестрация скачивания, фильтрации и очистки исходного архива."""

from pathlib import Path

from filtering import filter_log
from operation_state import OperationCancelled


def process_s3_log(archive, destination, rules, keep_raw, download, progress=None,
                   checkpoint=None, filterer=filter_log):
    """Скачать и отфильтровать лог, затем при необходимости удалить новый архив.

    Архив, существовавший до начала операции, функция никогда не удаляет. Любая
    ошибка скачивания или фильтрации также происходит до шага очистки.
    """
    archive = Path(archive).expanduser()
    existed_before = archive.exists()
    try:
        source = Path(download()).expanduser()
        if source.resolve() != archive.resolve():
            raise ValueError("Скачивание вернуло неожиданный путь архива")

        result = filterer(source, destination, rules, progress, checkpoint)
        removed = False
        if not keep_raw and not existed_before:
            source.unlink()
            removed = True
        return result, removed, existed_before
    except OperationCancelled:
        # Удаляем только готовый архив, созданный именно этой операцией.
        if not existed_before:
            archive.unlink(missing_ok=True)
        raise


def process_local_log(source, destination, rules, progress=None, checkpoint=None,
                      filterer=filter_log):
    """Отфильтровать локальный файл, не изменяя и не удаляя источник."""
    return filterer(source, destination, rules, progress, checkpoint)
