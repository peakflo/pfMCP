from datetime import timedelta
from uuid import uuid4

import google.auth
from google.auth.transport import requests as google_auth_requests
from google.cloud import storage as gcs_storage

from src.utils.storage.base import StorageService


class GCSStorageService(StorageService):
    def __init__(self, bucket_name: str, client: gcs_storage.Client):
        self._bucket = client.bucket(bucket_name)
        self._credentials, _ = google.auth.default()

    def upload_temporary(
        self, data: bytes, filename: str, mime_type: str, ttl_seconds: int = 3600
    ) -> str:
        blob_path = f"attachments/{uuid4()}/{filename}"
        blob = self._bucket.blob(blob_path)
        blob.upload_from_string(data, content_type=mime_type)

        # Refresh credentials to get a valid access token, then use
        # IAM signBlob API instead of local signing (Cloud Run
        # credentials don't have a private key).
        auth_request = google_auth_requests.Request()
        self._credentials.refresh(auth_request)

        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_seconds),
            method="GET",
            service_account_email=self._credentials.service_account_email,
            access_token=self._credentials.token,
        )
        return signed_url
