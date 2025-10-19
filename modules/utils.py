# -*- coding: utf-8 -*-
"""
Utility functions for the Manga Manager.
"""
import logging
import re
import textwrap

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


class FrameFormatter(logging.Formatter):
    def format(self, record):
        formatted = super().format(record)
        msg = record.getMessage()
        if msg.startswith('center:'):
            content = msg[7:].strip()
            align = 'center'
        elif msg.startswith('left:'):
            content = msg[5:]
            align = 'left'
        elif msg.startswith('|') and msg.endswith('|'):
            # already formatted frame line
            content = None
            msg_part = msg
        else:
            content = msg
            align = 'left'
        if content is not None:
            if len(content) > 98:
                lines = textwrap.wrap(content, width=98)
            else:
                lines = [content]
            msg_parts = []
            for line in lines:
                if align == 'center':
                    padded = line.center(100)
                else:
                    padded = (" " + line).ljust(100)
                msg_parts.append(f"|{padded}|")
            msg_part = "\n".join(msg_parts)
        level_end = formatted.rfind('] ') + 2
        return formatted[:level_end] + msg_part

def log_frame(msg, align='left'):
    prefix = 'left:' if align == 'left' else 'center:'
    if len(msg) > 98:
        lines = textwrap.wrap(msg, width=98)
    else:
        lines = [msg]
    for line in lines:
        logging.info(prefix + line)
