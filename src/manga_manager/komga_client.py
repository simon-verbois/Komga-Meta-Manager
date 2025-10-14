# -*- coding: utf-8 -*-
"""
Client for interacting with the Komga REST API.
"""
import json
import logging
from typing import List, Optional

import requests
from requests.exceptions import RequestException
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from manga_manager.config import KomgaConfig
from manga_manager.models import KomgaLibrary, KomgaSeries

# --- AMÉLIORATION: Définir les constantes ---
KOMGA_API_V1_PATH = "/api/v1"
# --- FIN DE L'AMÉLIORATION ---

class KomgaClient:
    """A client to fetch data from a Komga server."""
    
    def __init__(self, config: KomgaConfig):
        self.base_url = str(config.url).rstrip('/')
        self.headers = {
            "X-API-Key": config.api_key,
            "Accept": "application/json"
        }
        self.verify_ssl = config.verify_ssl
        self.session = requests.Session()
        
        logging.info(f"Komga Client initialized for URL: {self.base_url}")
        if not self.verify_ssl:
            logging.warning("SSL verification is disabled.")

    def _make_request(self, method: str, endpoint: str, params: Optional[dict] = None, json_data: Optional[dict] = None) -> Optional[dict | List]:
        """Helper method to make requests to the Komga API."""
        # --- AMÉLIORATION: Utiliser la constante ---
        url = f"{self.base_url}{KOMGA_API_V1_PATH}/{endpoint}"
        # --- FIN DE L'AMÉLIORATION ---
        try:
            response = self.session.request(
                method,
                url,
                headers=self.headers,
                params=params,
                json=json_data,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            return response.json() if response.content else {}
        except RequestException as e:
            logging.error(f"Error calling Komga API at {url}: {e}")
            return None
        except json.JSONDecodeError:
            logging.debug("API responded with success but no JSON body.")
            return {}


    def get_libraries(self) -> List[KomgaLibrary]:
        """
        Fetches all libraries from the Komga server.
        
        Returns:
            A list of library objects, or an empty list if the call fails.
        """
        logging.info("Fetching all libraries from Komga...")
        response_data = self._make_request("GET", "libraries")
        if isinstance(response_data, list):
            return [KomgaLibrary(**lib) for lib in response_data]
        return []

    def get_series_in_library(self, library_id: str, library_name: str) -> List[KomgaSeries]:
        """
        Fetches all series within a specific library, handling pagination.
        
        Args:
            library_id (str): The ID of the library to fetch series from.
            library_name (str): The name of the library for logging purposes.
            
        Returns:
            A list of series objects, or an empty list if none are found or an error occurs.
        """
        all_series = []
        page = 0
        logging.info(f"Fetching series for library: '{library_name}' (ID: {library_id})...")
        while True:
            params = {"library_id": library_id, "page": page, "size": 100}
            response_data = self._make_request("GET", "series", params=params)
            
            if not response_data or not isinstance(response_data, dict) or not response_data.get("content"):
                break
            
            series_page = [KomgaSeries(**series) for series in response_data.get("content", [])]
            all_series.extend(series_page)
            
            if response_data.get("last", True):
                break
            page += 1
        
        logging.info(f"Found {len(all_series)} series in library '{library_name}'.")
        return all_series

    def update_series_metadata(self, series_id: str, payload: dict) -> bool:
        """
        Updates the metadata for a specific series.
        
        Args:
            series_id (str): The ID of the series to update.
            payload (dict): A dictionary containing the metadata to update.
            
        Returns:
            True if the update was successful, False otherwise.
        """
        endpoint = f"series/{series_id}/metadata"
        response = self._make_request("PATCH", endpoint, json_data=payload)
        return response is not None

    def upload_series_poster(self, series_id: str, image_url: str) -> bool:
        """
        Uploads a poster for a series from a URL.
        
        Args:
            series_id (str): The ID of the series to update.
            image_url (str): The URL of the image to upload.
            
        Returns:
            True if the upload was successful, False otherwise.
        """
        try:
            image_response = self.session.get(image_url, stream=True, verify=self.verify_ssl)
            image_response.raise_for_status()
            
            files = {'file': (f"{series_id}_poster", image_response.content, 'image/jpeg')}
            
            url = f"{self.base_url}{KOMGA_API_V1_PATH}/series/{series_id}/thumbnails"
            
            api_response = self.session.post(url, headers=self.headers, files=files, verify=self.verify_ssl)
            api_response.raise_for_status()
            
            logging.info(f"Successfully uploaded poster for series ID {series_id} from {image_url}")
            return True
        except RequestException as e:
            logging.error(f"Failed to upload poster for series ID {series_id} from {image_url}: {e}")
            return False
