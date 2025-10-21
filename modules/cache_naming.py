# -*- coding: utf-8 -*-
"""
Cache filename generation utilities.
"""

def get_metadata_cache_filename(provider_name: str) -> str:
    """Generate metadata cache filename with provider name."""
    return f"metadata_provider_{provider_name}.json"


def get_translation_cache_filename(provider_name: str) -> str:
    """Generate translation cache filename with provider name."""
    return f"translation_provider_{provider_name}.json"
