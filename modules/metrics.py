# -*- coding: utf-8 -*-
"""
Metrics collection and reporting for the Manga Manager application.
"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from modules.output import get_output_manager

output_manager = get_output_manager()

@dataclass
class ProcessingMetrics:
    """
    Comprehensive metrics collection for a processing session.

    Tracks various performance indicators and completion statistics
    to provide insights into the processing job.
    """
    # Session timing
    session_start_time: float = field(default_factory=time.time)
    session_end_time: Optional[float] = None
    
    # Library and series counts
    libraries_processed: int = 0
    libraries_total: int = 0
    series_processed: int = 0
    series_total: int = 0
    
    # Processing results
    series_successful: int = 0
    series_failed: int = 0
    series_skipped: int = 0
    
    # API call counters
    komga_api_calls: int = 0
    komga_api_errors: int = 0
    anilist_api_calls: int = 0
    anilist_api_errors: int = 0
    translation_api_calls: int = 0
    translation_api_errors: int = 0
    
    # Cache statistics per component
    cache_hits: Dict[str, int] = field(default_factory=lambda: {'metadata': 0, 'translation': 0})
    cache_misses: Dict[str, int] = field(default_factory=lambda: {'metadata': 0, 'translation': 0})
    cache_sizes: Dict[str, int] = field(default_factory=lambda: {'metadata': 0, 'translation': 0})
    
    # Metadata update breakdown
    metadata_updates: Dict[str, int] = field(default_factory=lambda: {
        'summary': 0, 'genres': 0, 'tags': 0, 'status': 0, 'age_rating': 0, 'cover_image': 0
    })
    
    # Translation counters
    translations_performed: Dict[str, int] = field(default_factory=dict)  # lang -> count
    manual_translations_used: Dict[str, int] = field(default_factory=dict)  # lang -> count
    
    # Timing metrics
    average_series_processing_time: float = 0.0
    slowest_series_processing_time: float = 0.0
    slowest_series_name: str = ""
    
    # Error tracking
    errors: List[Dict] = field(default_factory=list)  # List of {'type': str, 'message': str, 'series_id': str}

    # Circuit breaker metrics
    circuit_breaker_states: Dict[str, Dict] = field(default_factory=dict)  # component -> {'state': str, 'transitions': int, 'failures': int}
    
    def mark_session_complete(self):
        """Mark the processing session as complete."""
        self.session_end_time = time.time()
    
    def add_library_processed(self, library_name: str):
        """Increment the libraries processed counter."""
        self.libraries_processed += 1
        output_manager.debug(f"Libraries processed: {self.libraries_processed}/{self.libraries_total}")
    
    def add_series_processed(self, series_name: str, success: bool = True, processing_time: float = 0.0):
        """Record processing of a single series."""
        self.series_processed += 1

        if success:
            self.series_successful += 1
        else:
            self.series_failed += 1

        # Update timing metrics
        if processing_time > 0:
            if self.series_successful + self.series_failed == 1:
                # First series
                self.average_series_processing_time = processing_time
            else:
                # Running average
                total_previous_time = self.average_series_processing_time * (self.series_successful + self.series_failed - 1)
                self.average_series_processing_time = (total_previous_time + processing_time) / (self.series_successful + self.series_failed)

            if processing_time > self.slowest_series_processing_time:
                self.slowest_series_processing_time = processing_time
                self.slowest_series_name = series_name
    
    def add_series_skipped(self, series_name: str):
        """Record a series that was skipped during processing."""
        self.series_skipped += 1
        output_manager.debug(f"Series skipped: '{series_name}'")
    
    def add_api_call(self, component: str, success: bool = True):
        """Record an API call for a specific component."""
        if component == 'komga':
            self.komga_api_calls += 1
            if not success:
                self.komga_api_errors += 1
        elif component == 'anilist':
            self.anilist_api_calls += 1
            if not success:
                self.anilist_api_errors += 1
        elif component == 'translation':
            self.translation_api_calls += 1
            if not success:
                self.translation_api_errors += 1
        else:
            output_manager.warning(f"Unknown component '{component}' for API call tracking")
    
    def add_cache_hit(self, cache_type: str):
        """Record a cache hit."""
        if cache_type in self.cache_hits:
            self.cache_hits[cache_type] += 1
        else:
            self.cache_hits[cache_type] = 1
    
    def add_cache_miss(self, cache_type: str):
        """Record a cache miss."""
        if cache_type in self.cache_misses:
            self.cache_misses[cache_type] += 1
        else:
            self.cache_misses[cache_type] = 1
    
    def set_cache_size(self, cache_type: str, size: int):
        """Set the final size of a cache."""
        self.cache_sizes[cache_type] = size
    
    def add_metadata_update(self, field_type: str):
        """Record a metadata field update."""
        if field_type in self.metadata_updates:
            self.metadata_updates[field_type] += 1
        else:
            self.metadata_updates[field_type] = 1

    def add_metadata_removal(self, field_type: str):
        """Record a metadata field removal."""
        if not hasattr(self, 'metadata_removals'):
            self.metadata_removals = {
                'summary': 0, 'genres': 0, 'tags': 0, 'status': 0, 'age_rating': 0, 'cover_image': 0
            }
        if field_type in self.metadata_removals:
            self.metadata_removals[field_type] += 1
        else:
            self.metadata_removals[field_type] = 1
    
    def add_translation(self, target_language: str, manual: bool = False):
        """Record a translation being performed."""
        if manual:
            if target_language in self.manual_translations_used:
                self.manual_translations_used[target_language] += 1
            else:
                self.manual_translations_used[target_language] = 1
        else:
            if target_language in self.translations_performed:
                self.translations_performed[target_language] += 1
            else:
                self.translations_performed[target_language] = 1
    
    def add_error(self, error_type: str, message: str, series_id: str = None):
        """Record an error that occurred during processing."""
        error_entry = {
            'type': error_type,
            'message': message,
            'series_id': series_id
        }
        self.errors.append(error_entry)
        output_manager.warning(f"Error recorded: {error_type} - {message}")
    
    @property
    def session_duration(self) -> float:
        """Get the total session duration in seconds."""
        end_time = self.session_end_time or time.time()
        return end_time - self.session_start_time
    
    @property
    def success_rate(self) -> float:
        """Get the success rate as a percentage."""
        total_completed = self.series_successful + self.series_failed
        return (self.series_successful / total_completed * 100) if total_completed > 0 else 100.0
    
    @property
    def cache_hit_ratio(self) -> Dict[str, float]:
        """Calculate cache hit ratios for each cache type."""
        ratios = {}
        for cache_type in set(list(self.cache_hits.keys()) + list(self.cache_misses.keys())):
            hits = self.cache_hits.get(cache_type, 0)
            misses = self.cache_misses.get(cache_type, 0)
            total = hits + misses
            ratios[cache_type] = (hits / total * 100) if total > 0 else 0.0
        return ratios
    
    def log_summary(self):
        """
        Log a comprehensive summary of all collected metrics.

        This method generates a detailed report showing processing results,
        performance metrics, cache efficiency, and error summaries.
        """
        if not self.session_end_time:
            self.mark_session_complete()
        
        duration_minutes = self.session_duration / 60
        output_manager.header("Processing Metrics Summary", level=1)

        output_manager.info(f"Session Duration: {duration_minutes:.2f} minutes")

        # Library and series metrics
        output_manager.info("COMPREHENSIVE PROCESSING STATISTICS:")
        output_manager.info(f"  Libraries processed: {self.libraries_processed}/{self.libraries_total}")
        output_manager.info(f"  Series processed: {self.series_processed}/{self.series_total}")
        output_manager.info(f"  Series successful: {self.series_successful}")
        output_manager.info(f"  Series failed: {self.series_failed}")
        output_manager.info(f"  Series skipped: {self.series_skipped}")

        if self.series_successful + self.series_failed > 0:
            output_manager.info(f"  Success rate: {self.success_rate:.1f}%")

        # API call metrics
        output_manager.info("API CALL STATISTICS:")
        output_manager.info(f"  Komga API calls: {self.komga_api_calls} (errors: {self.komga_api_errors})")
        output_manager.info(f"  AniList API calls: {self.anilist_api_calls} (errors: {self.anilist_api_errors})")
        output_manager.info(f"  Translation API calls: {self.translation_api_calls} (errors: {self.translation_api_errors})")

        # Cache metrics
        output_manager.info("CACHE PERFORMANCE:")
        hit_ratios = self.cache_hit_ratio
        for cache_type, ratio in hit_ratios.items():
            hits = self.cache_hits.get(cache_type, 0)
            misses = self.cache_misses.get(cache_type, 0)
            size = self.cache_sizes.get(cache_type, 0)
            output_manager.info(f"  {cache_type.title()} Cache: {ratio:.1f}% hit ratio ({hits}/{hits+misses} hits, size: {size})")

        # Metadata updates
        output_manager.info("METADATA UPDATE BREAKDOWN:")
        total_updates = sum(self.metadata_updates.values())
        if total_updates > 0:
            output_manager.info(f"  Total metadata fields updated: {total_updates}")
            for field, count in self.metadata_updates.items():
                if count > 0:
                    output_manager.info(f"    {field}: {count}")
        else:
            output_manager.info("  No metadata updates performed")

        # Metadata removals
        if hasattr(self, 'metadata_removals'):
            total_removals = sum(self.metadata_removals.values())
            if total_removals > 0:
                output_manager.info(f"  Total metadata fields removed: {total_removals}")
                for field, count in self.metadata_removals.items():
                    if count > 0:
                        output_manager.info(f"    {field}: {count}")

        # Translation statistics
        output_manager.info("TRANSLATION STATISTICS:")
        if self.translations_performed or self.manual_translations_used:
            total_translations = sum(self.translations_performed.values()) + sum(self.manual_translations_used.values())
            output_manager.info(f"  Total translations performed: {total_translations}")

            if self.manual_translations_used:
                manual_total = sum(self.manual_translations_used.values())
                output_manager.info(f"  Manual translations used: {manual_total}")

            for lang in sorted(set(list(self.translations_performed.keys()) + list(self.manual_translations_used.keys()))):
                auto_count = self.translations_performed.get(lang, 0)
                manual_count = self.manual_translations_used.get(lang, 0)
                if auto_count > 0 or manual_count > 0:
                    output_manager.info(f"    {lang}: {auto_count} auto, {manual_count} manual")
        else:
            output_manager.info("  No translations performed")

        # Performance metrics
        output_manager.info("PERFORMANCE METRICS:")
        if self.series_successful + self.series_failed > 0:
            output_manager.info(f"  Average processing time per series: {self.average_series_processing_time:.2f}s")
            output_manager.info(f"  Slowest series: '{self.slowest_series_name}' ({self.slowest_series_processing_time:.2f}s)")
            output_manager.info(f"  Processing rate: {(self.series_successful + self.series_failed) / duration_minutes:.1f} series/minute")

        # Error summary
        if self.errors:
            output_manager.info(f"ERROR SUMMARY: {len(self.errors)} error(s) occurred")
            error_types = {}
            for error in self.errors:
                error_type = error['type']
                error_types[error_type] = error_types.get(error_type, 0) + 1

            for error_type, count in error_types.items():
                output_manager.info(f"  {error_type}: {count} occurrence(s)")
        else:
            output_manager.info("ERROR SUMMARY: No errors occurred")
