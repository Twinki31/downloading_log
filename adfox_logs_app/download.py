"""Возобновляемое скачивание из S3 через стандартные AWS-профили."""

from pathlib import Path
import os
import tempfile

from path_ownership import publish_file


DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024


class RemoteObjectChangedError(RuntimeError):
    """Удалённый объект нельзя безопасно продолжить из-за изменения."""


def _object_identity(client, bucket, key):
    response = client.head_object(Bucket=bucket, Key=key)
    size = response.get("ContentLength")
    if not isinstance(size, int) or size < 0:
        raise ValueError("S3 не сообщил корректный размер объекта")
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise ValueError("S3 не сообщил ETag объекта; безопасное продолжение невозможно")
    return size, etag, response.get("VersionId")


def download_log(date, hour, folder, endpoint, bucket, prefix, profile="", use_proxy=False,
                 progress=None, metadata=None, control=None,
                 chunk_size=DEFAULT_CHUNK_SIZE, publish=True, replace=False):
    """Скачать объект отдельными Range GET, безопасно прерываясь между порциями.

    При ``publish=False`` владение готовым staging-файлом передаётся вызывающему
    коду только после успешного закрытия S3-клиента. До успешного возврата файл
    принадлежит этой функции и удаляется при любой ошибке.
    """
    import boto3
    from botocore.config import Config

    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("Размер порции скачивания должен быть положительным")
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{date:%Y_%m_%d}_{hour:02d}.tsv.gz"
    destination = folder / filename
    key = "/".join(x for x in (prefix.strip("/"), filename) if x)
    session = boto3.Session(profile_name=profile or None)
    config = Config(
        proxies=None if use_proxy else {}, retries={"max_attempts": 3},
        connect_timeout=15, read_timeout=60,
    )
    client = session.client("s3", endpoint_url=endpoint, config=config)
    temporary = None
    primary_error = None
    transfer_temporary = False
    try:
        fd, temporary_name = tempfile.mkstemp(dir=folder, suffix=".part")
        temporary = Path(temporary_name)
        os.close(fd)
        identity = _object_identity(client, bucket, key)
        total_bytes, etag, _version_id = identity
        if metadata:
            metadata(total_bytes if total_bytes > 0 else None)
        if control:
            control.check_cancelled()

        offset = 0
        with temporary.open("wb") as output:
            while offset < total_bytes:
                resumed = control.wait_download_permission() if control else False
                if resumed and _object_identity(client, bucket, key) != identity:
                    raise RemoteObjectChangedError(
                        "Объект S3 изменился во время паузы; продолжение остановлено"
                    )
                if control:
                    control.check_cancelled()

                end = min(offset + chunk_size, total_bytes) - 1
                request = {"Bucket": bucket, "Key": key,
                           "Range": f"bytes={offset}-{end}"}
                if etag:
                    request["IfMatch"] = etag
                try:
                    response = client.get_object(**request)
                except Exception as error:
                    details = getattr(error, "response", {})
                    code = str(details.get("Error", {}).get("Code", ""))
                    status = details.get("ResponseMetadata", {}).get("HTTPStatusCode")
                    if code in ("PreconditionFailed", "412") or status == 412:
                        raise RemoteObjectChangedError(
                            "Объект S3 изменился во время скачивания; операция остановлена"
                        ) from error
                    raise
                body = response["Body"]
                try:
                    data = body.read()
                finally:
                    body.close()
                expected = end - offset + 1
                if len(data) != expected:
                    raise OSError(
                        f"S3 вернул неполную порцию: ожидалось {expected}, получено {len(data)}"
                    )
                if control:
                    control.check_cancelled()
                output.write(data)
                offset += len(data)
                if progress:
                    progress(len(data))
        if publish:
            if control:
                control.finalize(
                    lambda: publish_file(temporary, destination, replace=replace)
                )
            else:
                publish_file(temporary, destination, replace=replace)
            result = destination
        else:
            # Ownership passes only after every mandatory cleanup action has
            # succeeded and the function can actually return this path.
            result = temporary
            transfer_temporary = True
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_errors = []
        try:
            client.close()
        except BaseException as error:
            cleanup_errors.append(("закрыть S3-клиент", error))
        if temporary is not None and (not transfer_temporary or cleanup_errors):
            try:
                temporary.unlink(missing_ok=True)
            except BaseException as error:
                cleanup_errors.append(("удалить временный файл", error))

        if transfer_temporary and not cleanup_errors:
            temporary = None

        if cleanup_errors:
            if primary_error is not None:
                for action, error in cleanup_errors:
                    primary_error.add_note(
                        f"Дополнительно не удалось {action}: {type(error).__name__}"
                    )
            else:
                cleanup_error = cleanup_errors[0][1]
                for action, error in cleanup_errors[1:]:
                    cleanup_error.add_note(
                        f"Дополнительно не удалось {action}: {type(error).__name__}"
                    )
                raise cleanup_error
    return result
