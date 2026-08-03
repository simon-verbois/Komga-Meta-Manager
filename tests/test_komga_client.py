from unittest.mock import Mock, patch

import pytest
import requests

from modules.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerState
from modules.config import KomgaConfig
from modules.constants import MAX_COVER_IMAGE_BYTES
from modules.komga_client import CoverImageError, KomgaAPIError, KomgaClient
from modules.models import KomgaThumbnail


def response(status: int, body: bytes = b"{}") -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = body
    result.url = "http://komga/api/v1/test"
    return result


def client() -> KomgaClient:
    return KomgaClient(
        KomgaConfig(url="http://komga:25600", api_key="secret", libraries=["Manga"])
    )


def thumbnail(identifier: str, *, kind: str = "USER_UPLOADED", size: int = 10) -> KomgaThumbnail:
    return KomgaThumbnail.model_validate(
        {
            "id": identifier,
            "seriesId": "series-1",
            "type": kind,
            "selected": True,
            "mediaType": "image/jpeg",
            "fileSize": size,
            "width": 100,
            "height": 200,
        }
    )


def test_429_is_retried() -> None:
    instance = client()
    instance.session.request = Mock(side_effect=[response(429), response(200)])
    with patch("modules.komga_client.time.sleep"):
        assert instance._make_request_with_retry("GET", "http://komga/test") == {}
    assert instance.session.request.call_count == 2


def test_retry_failure_opens_circuit_breaker() -> None:
    instance = client()
    instance.circuit_breaker = CircuitBreaker(
        CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60, name="test")
    )
    instance.session.request = Mock(side_effect=requests.Timeout("offline"))
    with patch("modules.komga_client.time.sleep"), pytest.raises(KomgaAPIError):
        instance._make_request("GET", "libraries")
    assert instance.circuit_breaker.state is CircuitBreakerState.OPEN


def test_existing_user_cover_is_preserved_without_overwrite() -> None:
    instance = client()
    instance.get_series_thumbnails = Mock(return_value=[thumbnail("old")])
    instance._download_cover_image = Mock()
    assert instance.update_series_poster("series-1", "https://image.test", False) == "preserved"
    instance._download_cover_image.assert_not_called()


def test_identical_cover_is_not_uploaded() -> None:
    instance = client()
    instance.get_series_thumbnails = Mock(return_value=[thumbnail("old")])
    instance._download_cover_image = Mock(return_value=(b"image", "image/jpeg", (10, 100, 200)))
    instance.session.post = Mock()
    assert instance.update_series_poster("series-1", "https://image.test", True) == "unchanged"
    instance.session.post.assert_not_called()


def test_new_cover_upload_does_not_delete_old_thumbnails() -> None:
    instance = client()
    instance.get_series_thumbnails = Mock(return_value=[thumbnail("old")])
    instance._download_cover_image = Mock(return_value=(b"image", "image/jpeg", (11, 100, 200)))
    instance.session.post = Mock(return_value=response(201))
    instance.delete_series_thumbnail = Mock()
    assert instance.update_series_poster("series-1", "https://image.test", True) == "uploaded"
    instance.delete_series_thumbnail.assert_not_called()


def test_explicit_cover_removal_deletes_only_user_uploads() -> None:
    instance = client()
    instance.get_series_thumbnails = Mock(
        return_value=[thumbnail("user"), thumbnail("generated", kind="GENERATED")]
    )
    instance.delete_series_thumbnail = Mock(return_value=True)
    assert instance.remove_uploaded_series_posters("series-1") == 1
    instance.delete_series_thumbnail.assert_called_once_with("series-1", "user")


def test_oversized_external_cover_is_rejected_with_tls_enabled() -> None:
    instance = client()
    remote = Mock()
    remote.headers = {"Content-Length": str(MAX_COVER_IMAGE_BYTES + 1)}
    instance.session.get = Mock(return_value=remote)

    with pytest.raises(CoverImageError):
        instance._download_cover_image("https://images.test/large.jpg")

    assert instance.session.get.call_args.kwargs["verify"] is True
    remote.close.assert_called_once()


def test_invalid_external_cover_is_rejected() -> None:
    instance = client()
    remote = Mock()
    remote.headers = {}
    remote.iter_content.return_value = [b"not an image"]
    instance.session.get = Mock(return_value=remote)
    with pytest.raises(CoverImageError, match="not a valid image"):
        instance._download_cover_image("https://images.test/invalid.jpg")
