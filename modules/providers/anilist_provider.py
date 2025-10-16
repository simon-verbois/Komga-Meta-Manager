# -*- coding: utf-8 -*-
"""
Provider for interacting with the AniList GraphQL API.
"""
import logging
from pathlib import Path
from typing import List

from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from gql.transport.exceptions import TransportQueryError

from modules.models import AniListMedia
from modules.constants import (
    ANILIST_API_URL,
    ANILIST_SEARCH_RESULTS_PER_PAGE,
    HTTP_TIMEOUTS,
    MAX_RETRIES
)
from .base import MetadataProvider
from modules.output import get_output_manager

output_manager = get_output_manager()

class AnilistProvider(MetadataProvider):
    """
    A provider to fetch manga metadata from the AniList GraphQL API.

    This provider searches for manga on AniList and retrieves comprehensive
    metadata including titles, descriptions, genres, tags, and cover images.
    Results are cached to minimize API calls.

    Attributes:
        client: The GraphQL client for AniList API
        cache_dir: Directory for storing cached responses
        cache_ttl_hours: Time-to-live for cache entries in hours
    """

    def __init__(self, cache_dir: Path, cache_ttl_hours: int):
        super().__init__(cache_dir, cache_ttl_hours)
        
        # Configure transport with timeouts and retries
        transport = RequestsHTTPTransport(
            url=ANILIST_API_URL,
            verify=True,
            retries=MAX_RETRIES,
            timeout=HTTP_TIMEOUTS[1]  # Use read timeout for GraphQL queries
        )
        
        self.client = Client(
            transport=transport,
            fetch_schema_from_transport=False
        )
        
        output_manager.info(f"AniList Provider initialized with {cache_ttl_hours}h cache TTL", "api")

    def _perform_search(self, search_term: str) -> List[AniListMedia]:
        """
        Perform the actual search for a manga on AniList.

        This method executes a GraphQL query to search for manga matching the
        given search term. Results are sorted by search relevance.

        Args:
            search_term: The manga title to search for

        Returns:
            A list of AniListMedia objects matching the search term.
            Returns an empty list if no results are found or an error occurs.

        Examples:
            >>> provider._perform_search("One Piece")
            [AniListMedia(id=30013, title=...), ...]

        Note:
            This method is called by the parent class's search() method,
            which handles caching. Direct calls will bypass the cache.
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
                        staff {
                            edges {
                                role
                                node {
                                    name {
                                        full
                                    }
                                }
                            }
                        }
                        popularity
                        tags {
                            name
                            rank
                        }
                        isAdult
                        coverImage {
                            extraLarge
                            large
                            medium
                        }
                    }
                }
            }
        """)

        params = {
            "search": search_term,
            "type": "MANGA",
            "perPage": ANILIST_SEARCH_RESULTS_PER_PAGE
        }

        try:
            output_manager.info(f"Searching AniList for manga: '{search_term}'", "api")
            result = self.client.execute(query, variable_values=params)

            output_manager.debug(f"Raw AniList response for '{search_term}': {result}")

            if result and result.get('Page') and result['Page'].get('media'):
                media_list = result['Page']['media']
                validated_media = []

                # Validate each media item individually to avoid losing all results
                # if one item is malformed
                for media_item in media_list:
                    try:
                        validated_media.append(AniListMedia.model_validate(media_item))
                    except Exception as e:
                        output_manager.warning(
                            f"Failed to validate media item from AniList response: {e}. "
                            f"Skipping this result.",
                            "warning"
                        )

                output_manager.info(f"Found {len(validated_media)} valid results for '{search_term}'", "success")
                return validated_media
            else:
                output_manager.warning(f"No results found on AniList for '{search_term}'", "warning")
                return []

        except TransportQueryError as e:
            # GraphQL-specific errors (e.g., rate limiting, query syntax errors)
            output_manager.error(
                f"GraphQL error while querying AniList for '{search_term}': {e}. "
                "This may indicate rate limiting or an API issue.",
                "error"
            )
            return []
        except Exception as e:
            # Catch-all for network errors, timeouts, etc.
            output_manager.error(
                f"Unexpected error while querying AniList for '{search_term}': {e}",
                exc_info=True
            )
            return []
