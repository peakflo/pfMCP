from abc import ABC, abstractmethod


class StorageService(ABC):
    @abstractmethod
    def upload_temporary(
        self, data: bytes, filename: str, mime_type: str, ttl_seconds: int = 3600
    ) -> str:
        """Upload data and return a temporary download URL.

        Args:
            data: File content as bytes
            filename: Original filename
            mime_type: MIME type of the file
            ttl_seconds: URL expiration time in seconds (default: 1 hour)

        Returns:
            A temporary signed URL for downloading the file
        """
        pass
