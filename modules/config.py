# -*- coding: utf-8 -*-
"""
Handles loading and validation of the application's configuration file.
"""
import re
import logging
from typing import List, Optional
import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

logger = logging.getLogger(__name__)

CONFIG_PATH = "/config/config.yml"

class SchedulerConfig(BaseModel):
    """Pydantic model for scheduler settings."""
    enabled: bool = False
    run_at: str = "04:00"

    @field_validator('run_at')
    @classmethod
    def validate_run_at_format(cls, v: str) -> str:
        """Validate that run_at is in HH:MM format."""
        if not re.match(r'^[0-2]\d:[0-5]\d$', v):
            raise ValueError('run_at must be in HH:MM format')
        return v

class WatcherConfig(BaseModel):
    """Pydantic model for watcher settings."""
    enabled: bool = False
    polling_interval_minutes: int = 5

class SystemConfig(BaseModel):
    """Pydantic model for system settings."""
    dry_run: bool = True
    debug: bool = False
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)

class KomgaConfig(BaseModel):
    """Pydantic model for Komga server configuration."""
    url: HttpUrl
    api_key: str = Field(..., min_length=1)
    libraries: List[str] = Field(..., min_length=1)
    verify_ssl: bool = True

class CacheConfig(BaseModel):
    """Pydantic model for cache settings."""
    ttl_hours: int = 168  # Default to 7 days

class ProviderConfig(BaseModel):
    """Pydantic model for metadata provider settings."""
    name: str = "anilist"
    min_score: int = 80
    cache: CacheConfig = Field(default_factory=CacheConfig)

class AuthorsConfig(BaseModel):
    """Pydantic model for granular author configuration."""
    writers: bool = True
    pencillers: bool = True

class TagsConfig(BaseModel):
    """Pydantic model for tags configuration."""
    score: bool = False

class UpdateFlags(BaseModel):
    """Pydantic model for granular update control."""
    summary: bool = True
    genres: bool = True
    status: bool = True
    authors: AuthorsConfig = Field(default_factory=AuthorsConfig)
    cover_image: bool = True
    tags: TagsConfig = Field(default_factory=TagsConfig)
    link: bool = False

class ProcessingConfig(BaseModel):
    """Pydantic model for metadata processing logic."""
    overwrite_existing: bool = False
    force_unlock: bool = False
    exclude_series: List[str] = Field(default_factory=list)
    update_fields: UpdateFlags = Field(default_factory=UpdateFlags)
    remove_fields: UpdateFlags = Field(default_factory=UpdateFlags)

    @model_validator(mode='after')
    @classmethod
    def enforce_remove_priority(cls, v):
        """Enforce that if remove_fields is true for a field, update_fields is automatically set to false."""
        if v.remove_fields.authors.writers and v.update_fields.authors.writers:
            logger.warning("Config validation: 'remove_fields.authors.writers' is true, forcing 'update_fields.authors.writers' to false.")
            v.update_fields.authors.writers = False
        if v.remove_fields.authors.pencillers and v.update_fields.authors.pencillers:
            logger.warning("Config validation: 'remove_fields.authors.pencillers' is true, forcing 'update_fields.authors.pencillers' to false.")
            v.update_fields.authors.pencillers = False
        if v.remove_fields.summary and v.update_fields.summary:
            logger.warning("Config validation: 'remove_fields.summary' is true, forcing 'update_fields.summary' to false.")
            v.update_fields.summary = False
        if v.remove_fields.genres and v.update_fields.genres:
            logger.warning("Config validation: 'remove_fields.genres' is true, forcing 'update_fields.genres' to false.")
            v.update_fields.genres = False
        if v.remove_fields.status and v.update_fields.status:
            logger.warning("Config validation: 'remove_fields.status' is true, forcing 'update_fields.status' to false.")
            v.update_fields.status = False
        if v.remove_fields.cover_image and v.update_fields.cover_image:
            logger.warning("Config validation: 'remove_fields.cover_image' is true, forcing 'update_fields.cover_image' to false.")
            v.update_fields.cover_image = False
        if v.remove_fields.tags.score and v.update_fields.tags.score:
            logger.warning("Config validation: 'remove_fields.tags.score' is true, forcing 'update_fields.tags.score' to false.")
            v.update_fields.tags.score = False
        if v.remove_fields.link and v.update_fields.link:
            logger.warning("Config validation: 'remove_fields.link' is true, forcing 'update_fields.link' to false.")
            v.update_fields.link = False

        return v

class DeepLConfig(BaseModel):
    """Pydantic model for DeepL specific settings."""
    api_key: str = Field(..., min_length=1)



class TranslationConfig(BaseModel):
    """Pydantic model for translation settings."""
    enabled: bool = True
    provider: str = "google"
    target_language: str = "en"
    deepl: Optional[DeepLConfig] = None

class AppConfig(BaseModel):
    """Root Pydantic model for the application configuration."""
    system: SystemConfig = Field(default_factory=SystemConfig)
    komga: KomgaConfig
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    translation: Optional[TranslationConfig] = None

def load_config(path: str = CONFIG_PATH) -> AppConfig:
    """
    Loads, parses, and validates the YAML configuration file.

    Args:
        path (str): The path to the configuration file.

    Returns:
        AppConfig: A validated configuration object.

    Raises:
        FileNotFoundError: If the config file does not exist.
        yaml.YAMLError: If the config file is not valid YAML.
        ValidationError: If the configuration does not match the schema.
    """
    with open(path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    return AppConfig(**config_data)
