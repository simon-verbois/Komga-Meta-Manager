# Path: src/manga_manager/providers/anilist_provider.py

# -*- coding: utf-8 -*-
"""
Provider for interacting with the AniList GraphQL API.
"""
import logging
from typing import List

from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from gql.transport.exceptions import TransportQueryError

from manga_manager.models import AniListMedia
from .base import MetadataProvider

logger = logging.getLogger(__name__)
ANILIST_API_URL = "https://graphql.anilist.co"

class AnilistProvider(MetadataProvider):
    """A provider to fetch data from the AniList GraphQL API."""

    def __init__(self):
        transport = RequestsHTTPTransport(url=ANILIST_API_URL, verify=True, retries=3)
        self.client = Client(transport=transport, fetch_schema_from_transport=False)
        logger.info("Anilist Provider initialized.")

    def search(self, search_term: str) -> List[AniListMedia]:
        """
        Searches for a manga on AniList and returns a list of potential matches.
        """
        query = gql("""
            query ($search: String, $type: MediaType, $perPage: Int) {
                Page (perPage: $perPage) {
                    media(search: $search, type: $type, sort: [SEARCH_MATCH]) {
                        id
                        title {
                            romaji
                            english
                            native
                        }
                        description(asHtml: false)
                        status
                        genres
                        popularity
                        tags {
                            name
                            rank
                        }
                        isAdult
                    }
                }
            }
        """)

        params = {"search": search_term, "type": "MANGA", "perPage": 5}

        try:
            logger.info(f"Searching AniList for manga: '{search_term}'")
            result = self.client.execute(query, variable_values=params)

            if result and result.get('Page') and result['Page'].get('media'):
                return [AniListMedia(**media_item) for media_item in result['Page']['media']]
            else:
                logger.warning(f"No results found on AniList for '{search_term}'")
                return []
        except TransportQueryError as e:
            logger.error(f"A GraphQL error occurred while querying AniList for '{search_term}': {e}")
            return []
        except Exception as e:
            logger.error(f"An unexpected error occurred while querying AniList for '{search_term}': {e}")
            return []