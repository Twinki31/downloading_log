"""Возобновляемое скачивание из S3 через стандартные AWS-профили."""

from pathlib import Path
import os
import tempfile


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
                 chunk_size=DEFAULT_CHUNK_SIZE, publish=True):
    """Скачать объект отдельными Range GET, безопасно прерываясь между порциями."""
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
    fd, temporary_name = tempfile.mkstemp(dir=folder, suffix=".part")
    os.close(fd)
    temporary = Path(temporary_name)
    try:
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
                control.finalize(lambda: os.replace(temporary, destination))
            else:
                os.replace(temporary, destination)
            result = destination
        else:
            # Ownership of the completed staging file passes to the caller.
            result = temporary
            temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        client.close()
    return result
