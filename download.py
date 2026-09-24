"""Скачивание из S3 через стандартные AWS-профили, без ключей в коде."""
from pathlib import Path
import os
import tempfile

def download_log(date, hour, folder, endpoint, bucket, prefix, profile="", use_proxy=False, progress=None):
    import boto3
    from botocore.config import Config
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{date:%Y_%m_%d}_{hour:02d}.tsv.gz"
    destination = folder / filename
    key = "/".join(x for x in (prefix.strip("/"), filename) if x)
    session = boto3.Session(profile_name=profile or None)
    config = Config(proxies=None if use_proxy else {}, retries={"max_attempts": 3}, connect_timeout=15, read_timeout=60)
    client = session.client("s3", endpoint_url=endpoint, config=config)
    fd, temporary = tempfile.mkstemp(dir=folder, suffix=".part")
    os.close(fd)
    try:
        # Скачивание последовательно: обновлять интерфейс из callback безопасно.
        from boto3.s3.transfer import TransferConfig
        client.download_file(bucket, key, temporary, Callback=progress,
                             Config=TransferConfig(use_threads=False))
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
        client.close()
    return destination
