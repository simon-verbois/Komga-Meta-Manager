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
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict:
        try:
            response = self.session.request(method, url, timeout=HTTP_TIMEOUTS, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise MetadataProviderError(
                    f"{type(self).__name__} returned an invalid JSON payload", reason="invalid_response"
                )
            return payload
        except MetadataProviderError:
            raise
        except requests.HTTPError as exc:
            response = exc.response
            status = response.status_code if response is not None else None
            reason = None
            if response is not None:
                try:
                    error = response.json().get("error", {})
                    if isinstance(error, dict):
                        errors = error.get("errors") or []
                        reason = (
                            errors[0].get("reason") if errors and isinstance(errors[0], dict) else None
                        ) or error.get("status")
                except (ValueError, AttributeError, TypeError):
                    pass
            if not isinstance(reason, str):
                reason = None
            message = f"{type(self).__name__} request failed (HTTP {status})"
            logger.warning(message)
            raise MetadataProviderError(message, status_code=status, reason=reason) from exc
        except (requests.RequestException, ValueError) as exc:
            reason = (
                "timeout"
                if isinstance(exc, requests.Timeout)
                else "connection"
                if isinstance(exc, requests.RequestException)
                else "invalid_response"
            )
            # Exception URLs and response bodies may contain credentials; keep diagnostics structured.
            message = f"{type(self).__name__} request failed ({reason})"
            logger.warning(message)
            raise MetadataProviderError(message, reason=reason) from exc
