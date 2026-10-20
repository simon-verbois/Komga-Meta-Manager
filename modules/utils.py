# -*- coding: utf-8 -*-
"""
Utility functions for the Manga Manager.
"""
import re

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


def clean_description(raw_text: str) -> str:
    """Convert the lightweight HTML/Markdown returned by providers to plain text."""
    text = clean_html(raw_text)
    text = re.sub(r'!\[([^]]*)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', text)
    text = re.sub(r'(?m)^\s*>\s?', '', text)
    text = re.sub(r'(?m)^\s*[-*_]{3,}\s*$', '', text)
    text = re.sub(r'[*_`~]+', '', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()
