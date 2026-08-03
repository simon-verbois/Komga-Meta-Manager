# -*- coding: utf-8 -*-
"""
Handles loading and validation of the application's configuration file.
"""
import logging
import os
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
        try:
            hour, minute = (int(part) for part in v.split(':'))
        except (AttributeError, TypeError, ValueError):
            raise ValueError('run_at must be in HH:MM format') from None
        if len(v) != 5 or v[2] != ':' or not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError('run_at must be a valid time in HH:MM format')
        return v

class WatcherConfig(BaseModel):
    """Pydantic model for watcher settings."""
    enabled: bool = False
    polling_interval_minutes: int = Field(default=5, gt=0)

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
    ttl_hours: int = Field(default=168, gt=0)  # Default to 7 days

class ProviderConfig(BaseModel):
    """Pydantic model for metadata provider settings."""
    name: str = "anilist"
    min_score: int = Field(default=80, ge=0, le=100)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    @field_validator('name')
    @classmethod
    def validate_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if provider != 'anilist':
            raise ValueError("provider.name must be 'anilist'")
        return provider

class AuthorsConfig(BaseModel):
    """Pydantic model for granular author configuration."""
    writers: bool = True
    pencillers: bool = True

class TagsConfig(BaseModel):
    """Pydantic model for tags configuration."""
    score: bool = False


class RemoveAuthorsConfig(BaseModel):
    """Author removal flags. Removals must always be opt-in."""
    writers: bool = False
    pencillers: bool = False


class RemoveFlags(BaseModel):
    """Metadata removal flags with safe, non-destructive defaults."""
    summary: bool = False
    genres: bool = False
    status: bool = False
    authors: RemoveAuthorsConfig = Field(default_factory=RemoveAuthorsConfig)
    cover_image: bool = False
    tags: TagsConfig = Field(default_factory=TagsConfig)
    link: bool = False

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
    remove_fields: RemoveFlags = Field(default_factory=RemoveFlags)

    @model_validator(mode='after')
    def enforce_remove_priority(self):
        """Enforce that if remove_fields is true for a field, update_fields is automatically set to false."""
        # Simple field mappings
        simple_fields = ['summary', 'genres', 'status', 'cover_image', 'link']

        for field in simple_fields:
            remove_val = getattr(self.remove_fields, field, False)
            update_val = getattr(self.update_fields, field, False)
            if remove_val and update_val:
                logger.warning(f"Config validation: 'remove_fields.{field}' is true, forcing 'update_fields.{field}' to false.")
                setattr(self.update_fields, field, False)

        # Handle nested author fields
        if self.remove_fields.authors.writers and self.update_fields.authors.writers:
            logger.warning("Config validation: 'remove_fields.authors.writers' is true, forcing 'update_fields.authors.writers' to false.")
            self.update_fields.authors.writers = False

        if self.remove_fields.authors.pencillers and self.update_fields.authors.pencillers:
            logger.warning("Config validation: 'remove_fields.authors.pencillers' is true, forcing 'update_fields.authors.pencillers' to false.")
            self.update_fields.authors.pencillers = False

        # Handle nested tags.score field
        if self.remove_fields.tags.score and self.update_fields.tags.score:
            logger.warning("Config validation: 'remove_fields.tags.score' is true, forcing 'update_fields.tags.score' to false.")
            self.update_fields.tags.score = False

        return self

class DeepLConfig(BaseModel):
    """Pydantic model for DeepL specific settings."""
    api_key: str = Field(..., min_length=1)



class TranslationConfig(BaseModel):
    """Pydantic model for translation settings."""
    enabled: bool = True
    provider: str = "google"
    target_language: str = "EN-US"
    deepl: Optional[DeepLConfig] = None

    @model_validator(mode='after')
    def validate_and_normalize(self):
        self.provider = self.provider.strip().lower()
        if self.provider not in {'google', 'deepl'}:
            raise ValueError("translation.provider must be 'google' or 'deepl'")
        if self.enabled and self.provider == 'deepl' and self.deepl is None:
            raise ValueError('translation.deepl.api_key is required when DeepL is enabled')

        language = self.target_language.strip().replace('_', '-')
        if not language:
            raise ValueError('translation.target_language must not be empty')
        if self.provider == 'google':
            language = language.lower()
            if language in {'en-us', 'en-gb'}:
                language = 'en'
        else:
            language = language.upper()
        self.target_language = language
        return self

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

    if not isinstance(config_data, dict):
        raise ValueError('Configuration root must be a YAML mapping')

    # Environment variables are the preferred way to inject secrets in
    # container orchestrators. They intentionally take precedence over YAML.
    komga_api_key = os.getenv('KMM_KOMGA_API_KEY')
    if komga_api_key:
        config_data.setdefault('komga', {})['api_key'] = komga_api_key

    deepl_api_key = os.getenv('KMM_DEEPL_API_KEY')
    if deepl_api_key:
        translation = config_data.setdefault('translation', {})
        if not isinstance(translation.get('deepl'), dict):
            translation['deepl'] = {}
        translation['deepl']['api_key'] = deepl_api_key

    return AppConfig(**config_data)
