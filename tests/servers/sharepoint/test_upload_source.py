"""Offline checks for upload_file URL downloads.

file_url is only accepted when it is an https GCS or S3 signed URL. Redirects
are re-checked, error bodies are never returned, and the read stops at the
size cap instead of buffering the whole response first.
"""

from src.servers.sharepoint.main import (
    _UploadSourceError,
    _download_file_url,
    _validate_download_url,
)

import pytest

GCS = "https://storage.googleapis.com/bucket/invoice.pdf?X-Goog-Signature=abc"
S3 = "https://bucket.s3.ap-southeast-1.amazonaws.com/invoice.pdf?X-Amz-Signature=abc"


class _Response:
    def __init__(self, status, headers=None, chunks=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = list(chunks) if chunks is not None else [body]
        self.closed = False
        self.read_calls = 0

    def iter_content(self, chunk_size=None):
        for chunk in self._chunks:
            self.read_calls += 1
            yield chunk

    def close(self):
        self.closed = True


def test_signed_gcs_and_s3_hosts_are_accepted():
    assert _validate_download_url(GCS) == GCS
    assert _validate_download_url(S3) == S3
    assert (
        _validate_download_url("https://bucket.storage.googleapis.com/file.pdf")
        == "https://bucket.storage.googleapis.com/file.pdf"
    )
    assert (
        _validate_download_url("https://s3.us-east-1.amazonaws.com/bucket/file.pdf")
        == "https://s3.us-east-1.amazonaws.com/bucket/file.pdf"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://storage.googleapis.com/bucket/file.pdf",
        "https://169.254.169.254/latest/meta-data/",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://localhost/file.pdf",
        "https://evil.com/file.pdf",
        "https://storage.googleapis.com.evil.com/file.pdf",
        "https://user:pass@storage.googleapis.com/file.pdf",
        "https://storage.googleapis.com:8443/file.pdf",
        "file:///etc/passwd",
    ],
)
def test_other_urls_are_rejected_before_a_request(url, monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("requests.get must not be called")

    monkeypatch.setattr(
        "src.servers.sharepoint.main.requests.get",
        fail_get,
    )
    with pytest.raises(_UploadSourceError):
        _download_file_url(url)


def test_successful_download_returns_bytes_and_does_not_send_auth(monkeypatch):
    seen = {}

    def fake_get(url, timeout, stream, allow_redirects):
        seen["url"] = url
        seen["kwargs"] = {
            "timeout": timeout,
            "stream": stream,
            "allow_redirects": allow_redirects,
        }
        return _Response(
            200,
            headers={
                "Content-Type": "application/pdf; charset=binary",
                "Content-Disposition": 'attachment; filename="invoice.pdf"',
            },
            body=b"%PDF",
        )

    monkeypatch.setattr("src.servers.sharepoint.main.requests.get", fake_get)
    content, name, content_type = _download_file_url(GCS)
    assert content == b"%PDF"
    assert name == "invoice.pdf"
    assert content_type == "application/pdf"
    assert seen["kwargs"] == {"timeout": 120, "stream": True, "allow_redirects": False}
    assert "headers" not in seen["kwargs"]


def test_error_status_does_not_include_the_body(monkeypatch):
    secret = b"internal token secret"

    def fake_get(url, timeout, stream, allow_redirects):
        return _Response(500, body=secret)

    monkeypatch.setattr("src.servers.sharepoint.main.requests.get", fake_get)
    with pytest.raises(_UploadSourceError) as caught:
        _download_file_url(GCS)
    assert "HTTP 500" in str(caught.value)
    assert b"internal token" not in str(caught.value).encode()
    assert "secret" not in str(caught.value)


def test_redirect_off_the_allowlist_is_not_followed(monkeypatch):
    calls = []

    def fake_get(url, timeout, stream, allow_redirects):
        calls.append(url)
        return _Response(
            302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
        )

    monkeypatch.setattr("src.servers.sharepoint.main.requests.get", fake_get)
    with pytest.raises(_UploadSourceError):
        _download_file_url(GCS)
    assert calls == [GCS]


def test_redirect_stays_on_an_allowed_host(monkeypatch):
    second = "https://storage.googleapis.com/bucket/other.pdf?X-Goog-Signature=next"
    calls = []

    def fake_get(url, timeout, stream, allow_redirects):
        calls.append(url)
        if url == GCS:
            return _Response(302, headers={"Location": second})
        return _Response(200, headers={"Content-Type": "application/pdf"}, body=b"ok")

    monkeypatch.setattr("src.servers.sharepoint.main.requests.get", fake_get)
    content, name, content_type = _download_file_url(GCS)
    assert calls == [GCS, second]
    assert content == b"ok"
    assert name == "other.pdf"
    assert content_type == "application/pdf"


def test_declared_size_over_the_cap_is_rejected_without_reading(monkeypatch):
    response = _Response(
        200,
        headers={"Content-Length": str(101 * 1024 * 1024)},
        chunks=[b"should-not-be-read"],
    )

    monkeypatch.setattr(
        "src.servers.sharepoint.main.requests.get",
        lambda *args, **kwargs: response,
    )
    with pytest.raises(_UploadSourceError) as caught:
        _download_file_url(GCS)
    assert "too large" in str(caught.value)
    assert response.read_calls == 0
    assert response.closed is True


def test_stream_stops_once_the_body_passes_the_cap(monkeypatch):
    monkeypatch.setattr("src.servers.sharepoint.main.MAX_UPLOAD_BYTES", 10)
    response = _Response(200, chunks=[b"123456", b"123456", b"123456"])

    monkeypatch.setattr(
        "src.servers.sharepoint.main.requests.get",
        lambda *args, **kwargs: response,
    )
    with pytest.raises(_UploadSourceError) as caught:
        _download_file_url(GCS)
    assert "too large" in str(caught.value)
    assert response.read_calls == 2
    assert response.closed is True
