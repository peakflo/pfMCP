import os
from uuid import uuid4

from src.utils.storage.base import StorageService


class LocalStorageService(StorageService):
    def __init__(self, storage_dir: str):
        self._storage_dir = storage_dir
        os.makedirs(self._storage_dir, exist_ok=True)

    def upload_temporary(
        self, data: bytes, filename: str, mime_type: str, ttl_seconds: int = 3600
    ) -> str:
        subdir = os.path.join(self._storage_dir, str(uuid4()))
        os.makedirs(subdir, exist_ok=True)
        file_path = os.path.join(subdir, filename)
        with open(file_path, "wb") as f:
            f.write(data)
        return f"file://{os.path.abspath(file_path)}"
