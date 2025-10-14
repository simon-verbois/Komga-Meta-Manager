# -*- coding: utf-8 -*-
"""
Pydantic models for structuring data from APIs.
"""
from typing import List, Optional, Set
from pydantic import BaseModel, Field

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
    genres: Set[str] = set()
    genres_lock: bool = Field(..., alias='genresLock')
    tags: Set[str] = set()
    tags_lock: bool = Field(..., alias='tagsLock')
    total_book_count: Optional[int] = Field(None, alias='totalBookCount')
    total_book_count_lock: bool = Field(..., alias='totalBookCountLock')

class KomgaSeries(BaseModel):
    id: str
    library_id: str = Field(..., alias='libraryId')
    name: str
    books_count: int = Field(..., alias='booksCount')
    metadata: KomgaSeriesMetadata

# --- AniList Models ---

class AniListTitle(BaseModel):
    romaji: Optional[str] = None
    english: Optional[str] = None
    native: Optional[str] = None

class AniListMedia(BaseModel):
    id: int
    title: AniListTitle
    description: Optional[str] = None
    status: Optional[str] = None
    genres: Optional[List[str]] = []
    tags: Optional[List[dict]] = []
    popularity: int = 0
    isAdult: bool = False