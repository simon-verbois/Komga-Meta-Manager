# -*- coding: utf-8 -*-
"""
Handles loading and validation of the application's configuration file.
"""
import re
from typing import List, Optional
import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator

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

class SystemConfig(BaseModel):
    """Pydantic model for system settings."""
    dry_run: bool = True
    debug: bool = False
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

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

class UpdateFlags(BaseModel):
    """Pydantic model for granular update control."""
    summary: bool = True
    genres: bool = True
    tags: bool = True
    status: bool = True
    age_rating: bool = True
    cover_image: bool = True

class ProcessingConfig(BaseModel):
    """Pydantic model for metadata processing logic."""
    overwrite_existing: bool = False
    force_unlock: bool = False
    exclude_series: List[str] = Field(default_factory=list)
    skip_series_with_summary: bool = False
    update_fields: UpdateFlags = Field(default_factory=UpdateFlags)

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
