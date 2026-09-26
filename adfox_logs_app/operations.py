"""Оркестрация скачивания, фильтрации и очистки исходного архива."""

from pathlib import Path

from filtering import filter_log
from operation_state import OperationCancelled
from path_ownership import publish_file


def process_s3_log(archive, destination, rules, keep_raw, download, progress=None,
                   checkpoint=None, finalize=None, filterer=filter_log,
                   replace=False):
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
                if source_is_archive:
                    publish_result()
                    if removed:
                        source.unlink()
                elif keep_raw:
                    # Архив публикуем первым: если этот шаг не удастся, старый
                    # итоговый TSV ещё не затронут. Итоговый TSV всегда
                    # остаётся последней публикацией успешной операции.
                    publish_file(source, archive, replace=replace)
                    publish_result()
                else:
                    publish_result()
                    source.unlink()

            if finalize:
                finalize(commit_all)
            else:
                commit_all()

        result = filterer(
            source, destination, rules, progress, checkpoint, commit_result,
            replace=replace,
        )
        source = None
        return result, removed, existed_before
    except OperationCancelled:
        # Удаляем только архив/part, созданный именно этой операцией.
        if source is not None and staged_source and source.exists():
            source.unlink(missing_ok=True)
        elif not existed_before:
            archive.unlink(missing_ok=True)
        raise
    except Exception:
        # Новый полностью скачанный архив полезен для диагностики. Старый архив
        # при ошибке не заменяем подготовленной копией.
        if source is not None and staged_source:
            if not existed_before:
                try:
                    publish_file(source, archive, replace=replace)
                finally:
                    source.unlink(missing_ok=True)
            else:
                source.unlink(missing_ok=True)
        raise


def process_local_log(source, destination, rules, progress=None, checkpoint=None,
                      finalize=None, filterer=filter_log, replace=False):
    """Отфильтровать локальный файл, не изменяя и не удаляя источник."""
    return filterer(
        source, destination, rules, progress, checkpoint, finalize,
        replace=replace,
    )
