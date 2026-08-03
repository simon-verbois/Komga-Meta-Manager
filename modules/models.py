# -*- coding: utf-8 -*-
"""
Pydantic models for structuring data from APIs.
"""
from typing import Dict, List, Literal, Optional, Set, Union
from pydantic import BaseModel, Field, PrivateAttr

# --- Komga Models ---

class KomgaLibrary(BaseModel):
    id: str
    name: str

class KomgaSeriesMetadata(BaseModel):
    status: str
    status_lock: bool = Field(..., alias='statusLock')
    title: str
    title_lock: bool = Field(..., alias='titleLock')
    summary: str
    summary_lock: bool = Field(..., alias='summaryLock')
    reading_direction: Optional[str] = Field(None, alias='readingDirection')
    reading_direction_lock: bool = Field(..., alias='readingDirectionLock')
    publisher: str
    publisher_lock: bool = Field(..., alias='publisherLock')
    age_rating: Optional[int] = Field(None, alias='ageRating')
    age_rating_lock: bool = Field(..., alias='ageRatingLock')
    language: str
    language_lock: bool = Field(..., alias='languageLock')
    genres: Set[str] = Field(default_factory=set)
    genres_lock: bool = Field(..., alias='genresLock')
    tags: Set[str] = Field(default_factory=set)
    tags_lock: bool = Field(..., alias='tagsLock')
    links: List[dict] = Field(default_factory=list)
    links_lock: bool = Field(..., alias='linksLock')
    total_book_count: Optional[int] = Field(None, alias='totalBookCount')
    total_book_count_lock: bool = Field(..., alias='totalBookCountLock')

class KomgaSeries(BaseModel):
    id: str
    library_id: str = Field(..., alias='libraryId')
    name: str
    books_count: int = Field(..., alias='booksCount')
    metadata: KomgaSeriesMetadata

class KomgaBookMetadata(BaseModel):
    title: str
    title_lock: bool = Field(..., alias='titleLock')
    summary: str
    summary_lock: bool = Field(..., alias='summaryLock')
    number: Union[str, int]
    number_lock: bool = Field(..., alias='numberLock')
    number_sort: float = Field(..., alias='numberSort')
    number_sort_lock: bool = Field(..., alias='numberSortLock')
    release_date: Optional[str] = Field(None, alias='releaseDate')
    release_date_lock: bool = Field(..., alias='releaseDateLock')
    authors: List[dict] = Field(default_factory=list)
    authors_lock: bool = Field(..., alias='authorsLock')
    tags: Set[str] = set()
    tags_lock: bool = Field(..., alias='tagsLock')

class KomgaThumbnail(BaseModel):
    id: str
    series_id: str = Field(..., alias='seriesId')
    type: str  # e.g., "USER_UPLOADED"
    selected: bool
    media_type: str = Field(..., alias='mediaType')
    file_size: int = Field(..., alias='fileSize')
    width: int
    height: int

class KomgaBook(BaseModel):
    id: str
    series_id: str = Field(..., alias='seriesId')
    name: str
    number: Union[str, int]
    metadata: KomgaBookMetadata

# --- Provider-neutral metadata models ---

class MetadataCreator(BaseModel):
    name: str
    role: Literal["writer", "penciller"]


class MetadataCandidate(BaseModel):
    provider: str
    external_id: str
    titles: List[str] = Field(default_factory=list)
    adult: bool = False
    popularity: int = 0
    year: Optional[str] = None
    media_type: Optional[str] = None

    @property
    def display_title(self) -> str:
        return self.titles[0] if self.titles else self.external_id


class MetadataRecord(MetadataCandidate):
    description: Optional[str] = None
    description_language: Optional[str] = None
    publisher: Optional[str] = None
    status: Optional[Literal["ONGOING", "ENDED", "ABANDONED", "HIATUS"]] = None
    genres: List[str] = Field(default_factory=list)
    genre_languages: Dict[str, str] = Field(default_factory=dict)
    creators: List[MetadataCreator] = Field(default_factory=list)
    score: Optional[float] = None  # normalized to 0-100
    site_url: Optional[str] = None
    provider_links: Dict[str, str] = Field(default_factory=dict)
    cover_urls: List[str] = Field(default_factory=list)
    _field_sources: dict[str, str] = PrivateAttr(default_factory=dict)

    def source_provider(self, field_name: str) -> str:
        """Return the provider that supplied a normalized metadata field."""
        return self._field_sources.get(field_name, self.provider)

    def set_field_source(self, field_name: str, provider_name: str) -> None:
        """Record field provenance while building a provider fallback result."""
        self._field_sources[field_name] = provider_name
