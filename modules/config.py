# -*- coding: utf-8 -*-
"""
Handles loading and validation of the application's configuration file.
"""
import logging
import os
from string import Formatter
from typing import List, Literal, Optional
import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

logger = logging.getLogger(__name__)

CONFIG_PATH = "/config/config.yml"
SUPPORTED_METADATA_PROVIDERS = ("anilist", "mangadex", "mangaupdates")

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
    workflow: Literal["collect", "push", "both"] = "both"
    overwrite_local: bool = False
    dry_run: bool = True
    # Automatic runs always fetch into KMM; publishing to Komga without review is opt-in.
    auto_publish: bool = False
    debug: bool = False  # Legacy console verbosity; Activity collects application debug entries independently.
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)

    @model_validator(mode="before")
    @classmethod
    def migrate_auto_publish(cls, data):
        """Keep live automatic publication for configurations saved before auto_publish existed."""
        if isinstance(data, dict) and "auto_publish" not in data:
            data = {
                **data,
                "auto_publish": data.get("workflow", "both") in ("both", "push") and data.get("dry_run", True) is False,
            }
        return data

class KomgaConfig(BaseModel):
    """Pydantic model for Komga server configuration."""
    url: HttpUrl
    api_key: str = Field(..., min_length=1)
    libraries: List[str] = Field(default_factory=list)
    verify_ssl: bool = True

class CacheConfig(BaseModel):
    """Pydantic model for cache settings."""
    ttl_hours: int = Field(default=168, gt=0)  # Default to 7 days

class ProviderConfig(BaseModel):
    """Pydantic model for metadata provider settings."""
    enabled: bool = True
    name: str = "anilist"
    priority: int = Field(default=1, ge=1)
    min_score: int = Field(default=80, ge=0, le=100)
    allow_adult: bool = False
    preferred_language: str = Field(default="en", min_length=2)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    @field_validator('name')
    @classmethod
    def validate_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if provider not in SUPPORTED_METADATA_PROVIDERS:
            raise ValueError("provider name must be 'anilist', 'mangadex' or 'mangaupdates'")
        return provider

    @field_validator('preferred_language')
    @classmethod
    def normalize_preferred_language(cls, value: str) -> str:
        normalized = value.strip().replace('_', '-').lower()
        if len(normalized) < 2:
            raise ValueError("providers.preferred_language must not be empty")
        return normalized


def default_providers() -> List[ProviderConfig]:
    """Return every metadata provider in the default fallback order."""
    return [
        ProviderConfig(name=name, priority=priority)
        for priority, name in enumerate(SUPPORTED_METADATA_PROVIDERS, start=1)
    ]

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
    publisher: bool = False
    language: bool = False
    reading_direction: bool = False
    genres: bool = False
    status: bool = False
    authors: RemoveAuthorsConfig = Field(default_factory=RemoveAuthorsConfig)
    cover_image: bool = False
    tags: TagsConfig = Field(default_factory=TagsConfig)
    link: bool = False

class UpdateFlags(BaseModel):
    """Pydantic model for granular update control."""
    summary: bool = True
    publisher: bool = True
    genres: bool = True
    status: bool = True
    authors: AuthorsConfig = Field(default_factory=AuthorsConfig)
    cover_image: bool = True
    tags: TagsConfig = Field(default_factory=TagsConfig)
    link: bool = False

class BookTitleConfig(BaseModel):
    """Opt-in naming of displayed book titles; file names are never changed."""

    mode: Literal["off", "volume", "chapter", "series", "custom"] = "off"
    template: str = Field(default="{series} - Volume {number}", max_length=200)
    padding: int = Field(default=0, ge=0, le=4)

    @field_validator("template")
    @classmethod
    def validate_template(cls, value: str) -> str:
        """Allow only stable series and number placeholders, without format expressions."""
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("Enter a non-empty, single-line book title template")
        for _, field, spec, conversion in Formatter().parse(value):
            if field is not None and (field not in {"series", "number"} or spec or conversion):
                raise ValueError("Book titles support only {series} and {number}")
        return value


class ProcessingConfig(BaseModel):
    """Pydantic model for metadata processing logic."""
    overwrite_existing: bool = False
    force_unlock: bool = False
    exclude_series: List[str] = Field(default_factory=list)
    update_fields: UpdateFlags = Field(default_factory=UpdateFlags)
    remove_fields: RemoveFlags = Field(default_factory=RemoveFlags)
    book_titles: BookTitleConfig = Field(default_factory=BookTitleConfig)

    @model_validator(mode='after')
    def enforce_remove_priority(self):
        """Enforce that if remove_fields is true for a field, update_fields is automatically set to false."""
        # Simple field mappings
        simple_fields = ['summary', 'publisher', 'genres', 'status', 'cover_image', 'link']

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

class LibraryConfig(BaseModel):
    """Library-specific overrides, keyed by the stable Komga library ID."""
    name: str
    content_type: Literal["manga", "webtoon", "ebook"] = "manga"
    processing: Optional[ProcessingConfig] = None
    providers: Optional[List[ProviderConfig]] = None
    translation_enabled: Optional[bool] = None
    target_language: Optional[str] = None
    # Series skipped by this library, added to the effective processing exclusions.
    exclude_series: List[str] = Field(default_factory=list)

    @field_validator("providers")
    @classmethod
    def validate_sources(cls, value):
        if value is not None:
            names = [source.name for source in value]
            priorities = [source.priority for source in value]
            if len(names) != len(set(names)) or len(priorities) != len(set(priorities)):
                raise ValueError("Sources must have unique names and priorities")
        return value


class AppConfig(BaseModel):
    """Root Pydantic model for the application configuration."""
    system: SystemConfig = Field(default_factory=SystemConfig)
    komga: KomgaConfig
    library_settings: dict[str, LibraryConfig] = Field(default_factory=dict)
    providers: List[ProviderConfig] = Field(default_factory=default_providers)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    translation: Optional[TranslationConfig] = None

    @field_validator('providers')
    @classmethod
    def validate_providers(cls, providers: List[ProviderConfig]) -> List[ProviderConfig]:
        """Require all supported providers with unique priorities."""
        names = [provider.name for provider in providers]
        priorities = [provider.priority for provider in providers]
        expected = set(SUPPORTED_METADATA_PROVIDERS)

        if len(names) != len(set(names)):
            raise ValueError('providers must not contain duplicate names')
        if set(names) != expected:
            missing = sorted(expected - set(names))
            unknown = sorted(set(names) - expected)
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown: {', '.join(unknown)}")
            raise ValueError(f"providers must contain all supported providers ({'; '.join(details)})")
        if len(priorities) != len(set(priorities)):
            raise ValueError('providers must have unique priorities')

        return sorted(providers, key=lambda provider: provider.priority)

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


def config_for_library(config: AppConfig, library_id: str) -> AppConfig:
    """Resolve saved overrides without mutating the shared settings snapshot."""
    resolved = config.model_copy(deep=True)
    profile = resolved.library_settings.get(library_id)
    resolved.library_settings = {}
    if profile:
        if profile.processing is not None:
            resolved.processing = profile.processing.model_copy(deep=True)
        resolved.processing.exclude_series = list(
            dict.fromkeys([*resolved.processing.exclude_series, *profile.exclude_series])
        )
        if profile.providers is not None:
            resolved.providers = list(profile.providers)
            names = {source.name for source in resolved.providers}
            next_priority = max((source.priority for source in resolved.providers), default=0) + 1
            for name in SUPPORTED_METADATA_PROVIDERS:
                if name not in names:
                    resolved.providers.append(ProviderConfig(name=name, enabled=False, priority=next_priority))
                    next_priority += 1
        if profile.translation_enabled is not None:
            resolved.translation = resolved.translation or TranslationConfig(enabled=False)
            resolved.translation.enabled = profile.translation_enabled
        if profile.target_language and resolved.translation:
            resolved.translation.target_language = profile.target_language
    return resolved
