"""Фоновое выполнение операций без зависимости от Streamlit."""

from pathlib import Path

from download import download_log
from operations import process_local_log, process_s3_log


def run_s3_operation(state, *, selected_date, hour, folder, endpoint, bucket,
                     prefix, profile, proxy, archive, destination, rules,
                     keep_raw, downloader=download_log):
    """Скачать и отфильтровать архив, публикуя только безопасное состояние."""

    archive_existed_before = Path(archive).expanduser().exists()

    def download():
        source = downloader(
            selected_date, hour, folder, endpoint, bucket, prefix, profile, proxy,
            progress=state.add_downloaded, metadata=state.begin_download,
            control=state, publish=False,
        )
        try:
            state.begin_filtering()
        except Exception:
            source_path = Path(source).expanduser()
            archive_path = Path(archive).expanduser()
            is_archive = source_path.resolve() == archive_path.resolve()
            is_staging = (
                source_path.parent.resolve() == archive_path.parent.resolve()
                and source_path.suffix == ".part"
            )
            if is_staging or (is_archive and not archive_existed_before):
                source_path.unlink(missing_ok=True)
            raise
        return source

    result, archive_removed, existed_before = process_s3_log(
        archive, destination, rules, keep_raw, download,
        state.update_filtering, state.check_cancelled, state.finalize,
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
    result = process_local_log(
        source, destination, rules, state.update_filtering, state.check_cancelled,
        state.finalize,
    )
    return {
        "path": str(Path(destination).resolve()),
        "filter_result": result,
        "archive_note": "Локальный исходный файл оставлен без изменений.",
        "archive": None,
    }
