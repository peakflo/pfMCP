from datetime import timedelta
from uuid import uuid4

from google.cloud import storage as gcs_storage

from src.utils.storage.base import StorageService


class GCSStorageService(StorageService):
    def __init__(self, bucket_name: str, client: gcs_storage.Client):
        self._bucket = client.bucket(bucket_name)

    def upload_temporary(
        self, data: bytes, filename: str, mime_type: str, ttl_seconds: int = 3600
    ) -> str:
        blob_path = f"attachments/{uuid4()}/{filename}"
        blob = self._bucket.blob(blob_path)
        blob.upload_from_string(data, content_type=mime_type)
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_seconds),
            method="GET",
        )
        return signed_url
