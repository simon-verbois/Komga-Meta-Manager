# -*- coding: utf-8 -*-
"""
Centralized output system for the Manga Manager application.
"""
import logging
from enum import Enum
from typing import Optional, Dict, List, Any

from colorama import init, Fore, Back, Style

# Initialize colorama for Windows compatibility
init(autoreset=True)


class OutputVerbosity(Enum):
    QUIET = 0
    NORMAL = 1
    VERBOSE = 2


class OutputManager:
    """
    Centralized output manager for consistent logging and formatting.
    """

    def __init__(self, verbosity: OutputVerbosity = OutputVerbosity.NORMAL, use_colors: bool = True):
        self.verbosity = verbosity
        self.use_colors = use_colors
        self.logger = logging.getLogger(__name__)

        # Configure colors
        self.colors = {
            'success': Fore.GREEN if use_colors else '',
            'warning': Fore.YELLOW if use_colors else '',
            'error': Fore.RED if use_colors else '',
            'info': Fore.CYAN if use_colors else '',
            'header': Fore.BLUE + Style.BRIGHT if use_colors else '',
            'reset': Style.RESET_ALL if use_colors else '',
        }

        # Configure emojis/icons
        self.icons = {
            'success': '✅',
            'warning': '⚠️',
            'error': '❌',
            'info': 'ℹ️',
            'debug': '🔍',
            'processing': '⚙️',
            'library': '📚',
            'series': '📖',
            'book': '📄',
            'api': '🌐',
            'translation': '🌍',
            'cache': '💾',
        }

    def _format_message(self, message: str, color: str = '', icon: str = '') -> str:
        """Format message with color and icon."""
        formatted = message
        if icon and self.verbosity.value >= OutputVerbosity.NORMAL.value:
            formatted = f"{icon} {formatted}"
        if color:
            formatted = f"{color}{formatted}{self.colors['reset']}"
        return formatted

    def _log_if_verbose(self, level: str, message: str, *args, **kwargs):
        """Log message only if verbosity allows it."""
        if self.verbosity.value >= OutputVerbosity.NORMAL.value:
            getattr(self.logger, level)(message, *args, **kwargs)

    def info(self, message: str, icon: str = 'info'):
        """Log info message."""
        formatted = self._format_message(message, self.colors['info'], self.icons.get(icon, ''))
        self._log_if_verbose('info', formatted)
        print(formatted)

    def success(self, message: str, icon: str = 'success'):
        """Log success message."""
        formatted = self._format_message(message, self.colors['success'], self.icons.get(icon, ''))
        self._log_if_verbose('info', formatted)
        print(formatted)

    def warning(self, message: str, icon: str = 'warning'):
        """Log warning message."""
        formatted = self._format_message(message, self.colors['warning'], self.icons.get(icon, ''))
        self._log_if_verbose('warning', formatted)
        print(formatted)

    def error(self, message: str, icon: str = 'error'):
        """Log error message."""
        formatted = self._format_message(message, self.colors['error'], self.icons.get(icon, ''))
        self._log_if_verbose('error', formatted)
        print(formatted)

    def debug(self, message: str, icon: str = 'debug'):
        """Log debug message (only in verbose mode)."""
        if self.verbosity.value >= OutputVerbosity.VERBOSE.value:
            formatted = self._format_message(message, '', self.icons.get(icon, ''))
            self.logger.debug(formatted)
            print(f"DEBUG: {formatted}")

    def header(self, title: str, level: int = 1):
        """Print a formatted header."""
        if self.verbosity.value < OutputVerbosity.NORMAL.value:
            return

        border = "=" * 80
        if level == 1:
            formatted_title = self._format_message(f" {title} ", self.colors['header'])
            print(f"\n{border}")
            print(f"{formatted_title}")
            print(f"{border}")
        elif level == 2:
            formatted_title = self._format_message(f"--- {title} ---", self.colors['header'])
            print(f"\n{formatted_title}")
        elif level == 3:
            formatted_title = self._format_message(f" {title} ", self.colors['header'])
            underline = "-" * len(formatted_title.strip())
            print(f"\n{formatted_title}")
            print(underline)

    def separator(self):
        """Print a separator line."""
        if self.verbosity.value >= OutputVerbosity.NORMAL.value:
            print("-" * 60)

    def progress_start(self, message: str):
        """Start a progress indicator."""
        if self.verbosity.value >= OutputVerbosity.NORMAL.value:
            print(f"{self.icons['processing']} {message}...", end='', flush=True)

    def progress_end(self, success: bool = True):
        """End a progress indicator."""
        if self.verbosity.value >= OutputVerbosity.NORMAL.value:
            if success:
                print(f" {self.colors['success']}{self.icons['success']}{self.colors['reset']}")
            else:
                print(f" {self.colors['error']}{self.icons['error']}{self.colors['reset']}")

    def table(self, headers: List[str], rows: List[List[str]]):
        """Print a formatted table."""
        if self.verbosity.value < OutputVerbosity.NORMAL.value:
            return

        if not headers and not rows:
            return

        # Calculate column widths
        all_rows = [headers] + rows if headers else rows
        col_widths = []
        for i in range(len(all_rows[0])):
            col_width = max(len(str(row[i])) for row in all_rows)
            col_widths.append(col_width)

        # Print headers
        if headers:
            header_line = " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
            print(header_line)
            print("-+-".join("-" * w for w in col_widths))

        # Print rows
        for row in rows:
            row_line = " | ".join(f"{str(cell):<{w}}" for cell, w in zip(row, col_widths))
            print(row_line)

    def report_summary(self, title: str, stats: Dict[str, Any]):
        """Print a summary report."""
        self.header(title, level=2)
        for key, value in stats.items():
            print(f"{key}: {value}")

    def processing_summary(self, libraries_processed: int, series_processed: int,
                          series_successful: int, series_failed: int,
                          processing_time: float):
        """Print a processing summary."""
        self.header("Processing Summary", level=1)

        total_series = series_successful + series_failed
        success_rate = (series_successful / total_series * 100) if total_series > 0 else 0

        stats = {
            f"Libraries processed: {libraries_processed}",
            f"Series processed: {total_series}",
            f"Series successful: {series_successful}",
            f"Series failed: {series_failed}",
            f"Success rate: {success_rate:.1f}%",
            f"Processing time: {processing_time:.2f}s"
        }

        for stat in stats:
            self.info(stat, 'processing')

    def dry_run_report(self, processed_count: int, updated_series_report: Dict[str, List[str]]):
        """Print a formatted dry run report."""
        self.header("Dry Run Report", level=1)

        updated_count = len(updated_series_report)
        print(f"Series Processed: {processed_count}")
        print(f"Series to be Updated: {updated_count}")
        print()

        if not updated_series_report:
            self.success("No changes to be made.")
        else:
            for series_name, changes in sorted(updated_series_report.items()):
                print(f"Changes for '{series_name}':")
                for change in changes:
                    print(f"  {change}")
                print()

        self.separator()

    def set_verbosity(self, verbosity: OutputVerbosity):
        """Change verbosity level."""
        self.verbosity = verbosity

    def enable_colors(self, enabled: bool = True):
        """Enable or disable colors."""
        self.use_colors = enabled


# Global output manager instance
_output_manager = None


def get_output_manager() -> OutputManager:
    """Get the global output manager instance."""
    global _output_manager
    if _output_manager is None:
        _output_manager = OutputManager()
    return _output_manager


def set_output_manager(manager: OutputManager):
    """Set the global output manager instance."""
    global _output_manager
    _output_manager = manager
