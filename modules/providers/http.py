"""Shared resilient HTTP support for REST metadata providers."""
import logging
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from modules.constants import HTTP_TIMEOUTS, MAX_RETRIES
from .base import MetadataProvider, MetadataProviderError

logger = logging.getLogger(__name__)


class HttpMetadataProvider(MetadataProvider):
    def __init__(self, cache_dir: Path, cache_ttl_hours: int):
        super().__init__(cache_dir, cache_ttl_hours)
        version_path = Path(__file__).resolve().parents[2] / "VERSION"
        version = version_path.read_text(encoding="utf-8").strip()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"Komga-Meta-Manager/{version}"})
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict:
        try:
            response = self.session.request(method, url, timeout=HTTP_TIMEOUTS, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise MetadataProviderError(f"{type(self).__name__} returned an invalid JSON payload")
            return payload
        except MetadataProviderError:
            raise
        except (requests.RequestException, ValueError) as exc:
            logger.error("%s request failed: %s", type(self).__name__, exc)
            raise MetadataProviderError(f"{type(self).__name__} request failed: {exc}") from exc
