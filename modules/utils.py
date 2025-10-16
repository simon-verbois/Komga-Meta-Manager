# -*- coding: utf-8 -*-
"""
Utility functions for the Manga Manager.
"""
import re
from pathlib import Path
from modules.output import get_output_manager

output_manager = get_output_manager()

def clean_html(raw_html: str) -> str:
    """
    Removes HTML tags and other unwanted sections from a string.
    
    Args:
        raw_html (str): The input string containing HTML tags.
        
    Returns:
        A cleaned string.
    """
    if not raw_html:
        return ""
    
    # First, replace <br> tags with newlines for better paragraph handling
    text = re.sub('<br\\s*/?>', '\n', raw_html)
    
    # Remove all other HTML tags
    text = re.sub('<.*?>', '', text)
    
    # Remove "(Source: ...)" patterns, case-insensitive
    text = re.sub('\\(Source:.*?\\)', '', text, flags=re.IGNORECASE)
    
    # Remove "Note:" or "Notes:" sections and everything that follows.
    # This looks for "Note(s):" at the beginning of a line (case-insensitive)
    # and removes it along with the rest of the string content.
    text = re.sub(r'(?m)^\s*Notes?:.*', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Replace two or more consecutive newlines with just a single newline
    # This effectively removes all blank lines between paragraphs.
    text = re.sub(r'\n{2,}', '\n', text)
    
    # Clean up excess whitespace and newlines from the start and end
    return text.strip()


def load_app_version() -> str:
    """
    Loads the application version from the VERSION file.

    Returns:
        The version string, or "unknown" if the file cannot be read.
    """
    from modules.constants import VERSION_FILE

    try:
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            version = f.read().strip()
            if not version:
                output_manager.warning("VERSION file is empty. Using 'unknown' as default.")
                return "unknown"
            output_manager.info(f"Application version loaded: {version}")
            return version
    except FileNotFoundError:
        output_manager.warning(f"VERSION file not found at {VERSION_FILE}. Using 'unknown' as default.")
        return "unknown"
    except Exception as e:
        output_manager.error(f"Error reading VERSION file: {e}. Using 'unknown' as default.")
        return "unknown"
