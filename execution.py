"""Фоновое выполнение операций без зависимости от Streamlit."""

from pathlib import Path

from download import download_log
from operations import process_local_log, process_s3_log


def run_s3_operation(state, *, selected_date, hour, folder, endpoint, bucket,
                     prefix, profile, proxy, archive, destination, rules,
                     keep_raw, downloader=download_log):
    """Скачать и отфильтровать архив, публикуя только безопасное состояние."""

    def download():
        source = downloader(
            selected_date, hour, folder, endpoint, bucket, prefix, profile, proxy,
            progress=state.add_downloaded, metadata=state.begin_download,
        )
        state.begin_filtering()
        return source

    result, archive_removed, existed_before = process_s3_log(
        archive, destination, rules, keep_raw, download,
        state.update_filtering,
    )
    if archive_removed:
        archive_note = "Скачанный архив удалён после успешного сохранения итогового TSV."
    elif existed_before and not keep_raw:
        archive_note = "Архив не удалён: он существовал до начала этой операции."
    else:
        archive_note = f"Сырой архив сохранён: {Path(archive).resolve()}"
    return {
        "path": str(Path(destination).resolve()),
        "filter_result": result,
        "archive_note": archive_note,
        "archive": str(Path(archive).resolve()),
    }


def run_local_operation(state, *, source, destination, rules):
    """Отфильтровать локальный файл в том же worker."""
    state.begin_filtering()
    result = process_local_log(source, destination, rules, state.update_filtering)
    return {
        "path": str(Path(destination).resolve()),
        "filter_result": result,
        "archive_note": "Локальный исходный файл оставлен без изменений.",
        "archive": None,
    }
