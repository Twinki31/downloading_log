"""Оркестрация скачивания, фильтрации и очистки исходного архива."""

import os
from pathlib import Path

from filtering import filter_log
from operation_state import OperationCancelled


def process_s3_log(archive, destination, rules, keep_raw, download, progress=None,
                   checkpoint=None, finalize=None, filterer=filter_log):
    """Скачать и отфильтровать лог, затем при необходимости удалить новый архив.

    Архив, существовавший до начала операции, функция никогда не удаляет. Любая
    ошибка скачивания или фильтрации также происходит до шага очистки.
    """
    archive = Path(archive).expanduser()
    destination = Path(destination).expanduser()
    existed_before = archive.exists()
    source = None
    staged_source = False
    try:
        source = Path(download()).expanduser()
        source_is_archive = source.resolve() == archive.resolve()
        staged_source = (
            source.parent.resolve() == archive.parent.resolve()
            and source.suffix == ".part"
        )
        if not source_is_archive and not staged_source:
            raise ValueError("Скачивание вернуло неожиданный путь временного архива")

        removed = not keep_raw and not existed_before

        def commit_result(publish_result):
            def commit_all():
                publish_result()
                if source_is_archive:
                    if removed:
                        source.unlink()
                elif keep_raw:
                    os.replace(source, archive)
                else:
                    source.unlink()

            if finalize:
                finalize(commit_all)
            else:
                commit_all()

        result = filterer(
            source, destination, rules, progress, checkpoint, commit_result,
        )
        source = None
        return result, removed, existed_before
    except OperationCancelled:
        # Удаляем только архив/part, созданный именно этой операцией.
        if source is not None and staged_source:
            source.unlink(missing_ok=True)
        elif not existed_before:
            archive.unlink(missing_ok=True)
        raise
    except Exception:
        # Новый полностью скачанный архив полезен для диагностики. Старый архив
        # при ошибке не заменяем подготовленной копией.
        if source is not None and staged_source:
            if not existed_before:
                os.replace(source, archive)
            else:
                source.unlink(missing_ok=True)
        raise


def process_local_log(source, destination, rules, progress=None, checkpoint=None,
                      finalize=None, filterer=filter_log):
    """Отфильтровать локальный файл, не изменяя и не удаляя источник."""
    return filterer(source, destination, rules, progress, checkpoint, finalize)
