# -*- coding: utf-8 -*-
"""
Client for interacting with the Komga REST API.
"""
import json
import logging
import time
from typing import List, Optional, Tuple
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from PIL import Image
import io
import urllib3
from modules.utils import log_frame
from modules.config import KomgaConfig
from modules.models import KomgaLibrary, KomgaSeries, KomgaBook, KomgaThumbnail
from modules.constants import (
    KOMGA_API_V1_PATH,
    HTTP_TIMEOUTS,
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
    KOMGA_SERIES_PAGE_SIZE
)
from modules.circuit_breaker import create_circuit_breaker_config, CircuitBreakerException, circuit_breaker_factory

logger = logging.getLogger(__name__)

class KomgaClient:
    """
    A client to fetch data from a Komga server.

    This client handles all HTTP communications with the Komga API, including:
    - Automatic retries with exponential backoff for transient errors
    - Configurable timeouts to prevent hanging requests
    - SSL verification with optional bypass for self-signed certificates
    - Circuit breaker pattern for resilience against service failures

    Attributes:
        base_url: The base URL of the Komga server
        headers: Default headers for all requests
        verify_ssl: Whether to verify SSL certificates
        session: Persistent session for connection pooling
        circuit_breaker: Circuit breaker for resilience
    """

    def __init__(self, config: KomgaConfig):
        self.base_url = str(config.url).rstrip('/')
        self.headers = {
            "X-API-Key": config.api_key,
            "Accept": "application/json"
        }
        self.verify_ssl = config.verify_ssl
        self.session = requests.Session()

        # Initialize circuit breaker with default configuration
        circuit_breaker_config = create_circuit_breaker_config('komga')
        self.circuit_breaker = circuit_breaker_factory.get_circuit_breaker(circuit_breaker_config)
        logger.debug(f"Komga Client initialized with circuit breaker '{circuit_breaker_config.name}'")

        # Disable SSL warnings only if SSL verification is disabled
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.warning("SSL certificate verification is disabled. This is insecure and not recommended for production use.")

        logger.info(f"Komga Client initialized for URL: {self.base_url}")

    def _is_retryable_error(self, exception: Exception) -> bool:
        """
        Determine if an error is transient and worth retrying.

        Args:
            exception: The exception to evaluate

        Returns:
            True if the error is retryable, False otherwise
        """
        # Retry on network errors and server errors (5xx)
        if isinstance(exception, (Timeout, ConnectionError)):
            return True
        
        if isinstance(exception, RequestException):
            response = getattr(exception, 'response', None)
            if response is not None:
                # Retry on server errors (500-599)
                return 500 <= response.status_code < 600
        
        return False

    def _make_request(self, method: str, endpoint: str, params: Optional[dict] = None, json_data: Optional[dict] = None) -> Optional[dict | List]:
        """
        Make HTTP requests to the Komga API with retry logic.

        This method implements exponential backoff for transient errors like network
        timeouts or server errors (5xx). Permanent errors (4xx) are not retried.

        Args:
            method: HTTP method (GET, POST, PATCH, etc.)
            endpoint: API endpoint path (without base URL)
            params: Optional query parameters
            json_data: Optional JSON body for POST/PATCH requests

        Returns:
            Parsed JSON response as dict/list, empty dict for successful requests
            with no body, or None if the request ultimately fails

        Examples:
            >>> client._make_request("GET", "libraries")
            [{"id": "lib1", "name": "Manga"}, ...]

            >>> client._make_request("PATCH", "series/123/metadata", json_data={"summary": "New"})
            {}
        """
        url = f"{self.base_url}{KOMGA_API_V1_PATH}/{endpoint}"
        last_exception = None

        # Wrap the entire request logic in circuit breaker if available
        if self.circuit_breaker:
            try:
                return self.circuit_breaker.call(self._make_request_with_retry, method, url, params, json_data)
            except Exception as e:
                logger.error(f"Circuit breaker blocked or failed request to {url}: {e}")
                return None

        # Fallback to direct call without circuit breaker protection
        return self._make_request_with_retry(method, url, params, json_data)

    def _make_request_with_retry(self, method: str, url: str, params: Optional[dict] = None, json_data: Optional[dict] = None) -> Optional[dict | List]:
        """Internal method that performs the actual HTTP request with retries."""

        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(f"Request attempt {attempt + 1}/{MAX_RETRIES}: {method} {url}")

                response = self.session.request(
                    method,
                    url,
                    headers=self.headers,
                    params=params,
                    json=json_data,
                    verify=self.verify_ssl,
                    timeout=HTTP_TIMEOUTS
                )
                response.raise_for_status()

                # Success - return parsed JSON or empty dict
                return response.json() if response.content else {}

            except json.JSONDecodeError as e:
                logger.debug("API responded with success but no JSON body.")
                return {}

            except RequestException as e:
                last_exception = e

                # Check if this is a permanent error (4xx except 429)
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code

                    # Don't retry client errors (except 429 Too Many Requests)
                    if 400 <= status_code < 500 and status_code != 429:
                        logger.error(f"Client error calling Komga API at {url}: {status_code} - {e}")
                        return None

                # Check if we should retry
                if not self._is_retryable_error(e):
                    logger.error(f"Non-retryable error calling Komga API at {url}: {e}")
                    return None

                # This is a retryable error
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BACKOFF_FACTOR ** attempt
                    logger.warning(
                        f"Retryable error on attempt {attempt + 1}/{MAX_RETRIES} for {url}: {e}. "
                        f"Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Request failed after {MAX_RETRIES} attempts for {url}: {e}"
                    )
        
        # All retries exhausted
        return None


    def get_libraries(self) -> List[KomgaLibrary]:
        """
        Fetch all libraries from the Komga server.

        Returns:
            A list of library objects, or an empty list if the call fails or
            the server is unreachable.

        Examples:
            >>> client.get_libraries()
            [KomgaLibrary(id='1', name='Manga'), KomgaLibrary(id='2', name='Comics')]
        """
        logging.info("|                                                                                                    |")
        logging.info("|====================================================================================================|")
        log_frame("Libraries", 'center')
        logging.info("|====================================================================================================|")
        logger.info("Fetching all libraries from Komga...")
        response_data = self._make_request("GET", "libraries")

        if isinstance(response_data, list):
            logger.info(f"Successfully retrieved {len(response_data)} libraries")
            return [KomgaLibrary(**lib) for lib in response_data]

        logger.error("Failed to retrieve libraries from Komga")
        return []

    def get_series_in_library(self, library_id: str, library_name: str) -> List[KomgaSeries]:
        """
        Fetch all series within a specific library, handling pagination.

        This method automatically handles pagination to retrieve all series,
        making multiple requests if necessary.

        Args:
            library_id: The ID of the library to fetch series from
            library_name: The name of the library (used for logging only)

        Returns:
            A list of series objects, or an empty list if none are found,
            an error occurs, or the library is empty

        Examples:
            >>> client.get_series_in_library("lib1", "Manga")
            [KomgaSeries(...), KomgaSeries(...), ...]
        """
        all_series = []
        page = 0
        logger.info(f"Fetching series for library: '{library_name}' (ID: {library_id})...")

        while True:
            params = {
                "library_id": library_id,
                "page": page,
                "size": KOMGA_SERIES_PAGE_SIZE
            }
            response_data = self._make_request("GET", "series", params=params)

            if not response_data or not isinstance(response_data, dict):
                if page == 0:
                    logger.error(f"Failed to fetch series from library '{library_name}'")
                break

            content = response_data.get("content", [])
            if not content:
                break

            series_page = [KomgaSeries(**series) for series in content]
            all_series.extend(series_page)
            logger.debug(f"Fetched page {page + 1} with {len(series_page)} series")

            if response_data.get("last", True):
                break
            page += 1
        
        logger.info(f"Found {len(all_series)} series in library '{library_name}'.")
        return all_series

    def update_series_metadata(self, series_id: str, payload: dict) -> bool:
        """
        Update the metadata for a specific series.

        Args:
            series_id: The ID of the series to update
            payload: A dictionary containing the metadata fields to update.
                     Can include: summary, genres, tags, status, ageRating, etc.

        Returns:
            True if the update was successful, False otherwise

        Examples:
            >>> client.update_series_metadata("series123", {
            ...     "summary": "A great manga",
            ...     "genres": ["Action", "Adventure"],
            ...     "summaryLock": False
            ... })
            True
        """
        endpoint = f"series/{series_id}/metadata"
        logger.debug(f"Updating metadata for series {series_id}: {list(payload.keys())}")
        response = self._make_request("PATCH", endpoint, json_data=payload)
        
        if response is not None:
            logger.debug(f"Successfully updated metadata for series {series_id}")
            return True
        
        logger.error(f"Failed to update metadata for series {series_id}")
        return False

    def get_books_in_series(self, series_id: str, series_name: str) -> List[KomgaBook]:
        """
        Fetch all books within a specific series, handling pagination.

        This method automatically handles pagination to retrieve all books,
        making multiple requests if necessary.

        Args:
            series_id: The ID of the series to fetch books from
            series_name: The name of the series (used for logging only)

        Returns:
            A list of book objects, or an empty list if none are found or an error occurs

        Examples:
            >>> client.get_books_in_series("series1", "Naruto")
            [KomgaBook(...), KomgaBook(...), ...]
        """
        all_books = []
        page = 0
        logger.info(f"Fetching books for series: '{series_name}' (ID: {series_id})...")

        while True:
            params = {
                "page": page,
                "size": KOMGA_SERIES_PAGE_SIZE  # Reuse the same page size constant
            }
            response_data = self._make_request("GET", f"series/{series_id}/books", params=params)

            if not response_data or not isinstance(response_data, dict):
                if page == 0:
                    logger.error(f"Failed to fetch books from series '{series_name}'")
                break

            content = response_data.get("content", [])
            if not content:
                break

            books_page = [KomgaBook(**book) for book in content]
            all_books.extend(books_page)
            logger.debug(f"Fetched page {page + 1} with {len(books_page)} books")

            if response_data.get("last", True):
                break
            page += 1

        logger.info(f"Found {len(all_books)} books in series '{series_name}'.")
        return all_books

    def update_book_metadata(self, book_id: str, payload: dict) -> bool:
        """
        Update the metadata for a specific book.

        Args:
            book_id: The ID of the book to update
            payload: A dictionary containing the metadata fields to update.
                     Can include: authors, tags, etc.

        Returns:
            True if the update was successful, False otherwise

        Examples:
            >>> client.update_book_metadata("book123", {
            ...     "authors": [{"name": "Tatsuki Fujimoto", "role": "writer"}],
            ...     "authorsLock": True
            ... })
            True
        """
        endpoint = f"books/{book_id}/metadata"
        logger.debug(f"Updating metadata for book {book_id}: {list(payload.keys())}")
        response = self._make_request("PATCH", endpoint, json_data=payload)

        if response is not None:
            logger.debug(f"Successfully updated metadata for book {book_id}")
            return True

        logger.error(f"Failed to update metadata for book {book_id}")
        return False

    def get_series_thumbnails(self, series_id: str) -> List[KomgaThumbnail]:
        """
        Fetch all thumbnails for a specific series.

        Args:
            series_id: The ID of the series to fetch thumbnails from

        Returns:
            A list of thumbnail objects, or an empty list if none are found or an error occurs

        Examples:
            >>> client.get_series_thumbnails("series1")
            [KomgaThumbnail(...), KomgaThumbnail(...), ...]
        """
        endpoint = f"series/{series_id}/thumbnails"
        logger.debug(f"Fetching thumbnails for series {series_id}")
        response_data = self._make_request("GET", endpoint)

        if isinstance(response_data, list):
            logger.debug(f"Successfully retrieved {len(response_data)} thumbnails for series {series_id}")
            return [KomgaThumbnail(**thumb) for thumb in response_data]

        logger.debug(f"No thumbnails found or failed to retrieve thumbnails for series {series_id}")
        return []



    def delete_series_thumbnail(self, series_id: str, thumbnail_id: str) -> bool:
        """
        Delete a specific thumbnail for a series.

        Args:
            series_id: The ID of the series
            thumbnail_id: The ID of the thumbnail to delete

        Returns:
            True if the deletion was successful, False otherwise

        Examples:
            >>> client.delete_series_thumbnail("series123", "thumb123")
            True
        """
        endpoint = f"series/{series_id}/thumbnails/{thumbnail_id}"
        logger.debug(f"Deleting thumbnail {thumbnail_id} for series {series_id}")
        response = self._make_request("DELETE", endpoint)

        if response is not None and isinstance(response, dict) and not response:
            # DELETE returns empty dict on success
            logger.debug(f"Successfully deleted thumbnail {thumbnail_id} for series {series_id}")
            return True

        logger.error(f"Failed to delete thumbnail {thumbnail_id} for series {series_id}")
        return False

    def clean_duplicate_thumbnails(self, series_id: str) -> int:
        """
        Clean duplicate thumbnails for a series based on fileSize, width, height.
        For each group of duplicates, keep only the one with the smallest ID.

        Args:
            series_id: The ID of the series

        Returns:
            Number of thumbnails deleted

        Examples:
            >>> client.clean_duplicate_thumbnails("series123")
            3  # Number of duplicates deleted
        """
        thumbnails = self.get_series_thumbnails(series_id)
        if not thumbnails:
            return 0

        from collections import defaultdict
        by_key = defaultdict(list)
        for thumb in thumbnails:
            key = (thumb.file_size, thumb.width, thumb.height)
            by_key[key].append(thumb)

        deleted_count = 0
        for key, thumbs in by_key.items():
            if len(thumbs) > 1:
                # Sort by ID ascending, keep the first, delete the rest
                thumbs_sorted = sorted(thumbs, key=lambda t: t.id)
                keep = thumbs_sorted[0]
                to_delete = thumbs_sorted[1:]
                for thumb in to_delete:
                    if self.delete_series_thumbnail(series_id, thumb.id):
                        deleted_count += 1

        if deleted_count > 0:
            logger.info(f"Supprimé {deleted_count} thumbnails dupliqués pour série {series_id}")
        return deleted_count

    def get_image_metadata(self, image_content: bytes) -> Optional[Tuple[int, int, int]]:
        """
        Extract metadata from image bytes: (file_size, width, height)

        Args:
            image_content: The raw image bytes

        Returns:
            Tuple of (file_size, width, height) or None if error

        Examples:
            >>> client.get_image_metadata(b'...')
            (123456, 800, 1200)
        """
        try:
            file_size = len(image_content)
            image = Image.open(io.BytesIO(image_content))
            width, height = image.size
            return file_size, width, height
        except Exception as e:
            logger.error(f"Failed to get image metadata: {e}")
            return None

    def thumbnail_exists(self, thumbnails: List[KomgaThumbnail], file_size: int, width: int, height: int) -> bool:
        """
        Check if a thumbnail with exact file_size, width, height exists.

        Args:
            thumbnails: List of existing thumbnails
            file_size: File size to check
            width: Image width
            height: Image height

        Returns:
            True if exists, False otherwise
        """
        for thumb in thumbnails:
            if thumb.file_size == file_size and thumb.width == width and thumb.height == height:
                return True
        return False

    def upload_series_poster(self, series_id: str, image_url: str) -> bool:
        """
        Download an image from a URL and upload/force it as the series poster.
        Always upload the new image and clean old thumbnails to keep only the new one.

        Args:
            series_id: The ID of the series to update
            image_url: The URL of the image to download and upload

        Returns:
            True if upload and cleanup succeeded, False on failure

        Examples:
            >>> client.upload_series_poster("series123", "https://example.com/cover.jpg")
            True
        """
        try:
            # Download image with timeout
            image_response = self.session.get(
                image_url,
                stream=True,
                verify=self.verify_ssl,
                timeout=HTTP_TIMEOUTS
            )
            image_response.raise_for_status()
            image_content = image_response.content

            # Prepare file for upload
            files = {'file': (f"{series_id}_poster", image_content, 'image/jpeg')}
            url = f"{self.base_url}{KOMGA_API_V1_PATH}/series/{series_id}/thumbnails"

            # Upload to Komga with timeout
            api_response = self.session.post(
                url,
                headers=self.headers,
                files=files,
                verify=self.verify_ssl,
                timeout=HTTP_TIMEOUTS
            )
            api_response.raise_for_status()

            # Get the created thumbnail from response
            try:
                created_thumb = api_response.json()
                if isinstance(created_thumb, dict) and 'id' in created_thumb:
                    thumb_id = created_thumb['id']
                    # Clean all other thumbnails
                    cleaned_count = self._clean_other_thumbnails(series_id, keep_thumb_id=thumb_id)
                    if cleaned_count > 0:
                        logger.info(f"Cleaned {cleaned_count} old thumbnails, kept new {thumb_id}")
                else:
                    logger.warning(f"Could not get uploaded thumbnail ID for series {series_id}")
            except Exception as e:
                logger.warning(f"Failed to parse upload response for series {series_id}: {e}")

            logger.info(f"Successfully uploaded and set new poster for series {series_id} from {image_url}")
            return True

        except Timeout as e:
            logger.error(f"Timeout while uploading poster for series {series_id} from {image_url}: {e}")
            return False
        except RequestException as e:
            logger.error(f"Failed to upload poster for series {series_id} from {image_url}: {e}")
            return False

    def _clean_other_thumbnails(self, series_id: str, keep_thumb_id: str) -> int:
        """
        Delete all thumbnails for the series except the one with keep_thumb_id.
        """
        thumbnails = self.get_series_thumbnails(series_id)
        deleted_count = 0
        for thumb in thumbnails:
            if thumb.id != keep_thumb_id:
                if self.delete_series_thumbnail(series_id, thumb.id):
                    deleted_count += 1
        return deleted_count
