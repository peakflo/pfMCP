import os
import logging

from src.utils.storage.base import StorageService

logger = logging.getLogger("storage-factory")

_storage_service_instance = None


def get_storage_service() -> StorageService:
    global _storage_service_instance

    if _storage_service_instance is not None:
        return _storage_service_instance

    provider = os.environ.get("STORAGE_PROVIDER", "gcs").lower()

    if provider == "local":
        from src.utils.storage.local import LocalStorageService

        storage_dir = os.environ.get("LOCAL_STORAGE_DIR", "/tmp/pfmcp-attachments")
        _storage_service_instance = LocalStorageService(storage_dir)
    elif provider == "gcs":
        from google.cloud import storage as gcs_storage

        from src.utils.storage.gcs import GCSStorageService

        bucket_name = os.environ.get("GCS_BUCKET_NAME")
        if not bucket_name:
            raise ValueError("GCS_BUCKET_NAME environment variable is required")

        client = gcs_storage.Client()
        _storage_service_instance = GCSStorageService(bucket_name, client)
    else:
        raise ValueError(f"Unsupported storage provider: {provider}")

    return _storage_service_instance
