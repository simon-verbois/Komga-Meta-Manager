# -*- coding: utf-8 -*-
"""
Tests for the metrics collection module.
"""
import time
import pytest
from manga_manager.metrics import ProcessingMetrics


class TestProcessingMetrics:
    """Test the metrics collection functionality."""

    def test_initialization(self):
        """Test that metrics are properly initialized."""
        metrics = ProcessingMetrics()

        assert metrics.session_start_time is not None
        assert metrics.session_end_time is None
        assert metrics.libraries_processed == 0
        assert metrics.series_successful == 0
        assert metrics.series_failed == 0
        assert metrics.series_skipped == 0

    def test_mark_session_complete(self):
        """Test marking session as complete."""
        metrics = ProcessingMetrics()
        original_start = metrics.session_start_time

        time.sleep(0.1)  # Small delay
        metrics.mark_session_complete()

        assert metrics.session_end_time is not None
        assert metrics.session_end_time > original_start
        assert metrics.session_duration > 0

    def test_add_library_processed(self):
        """Test incrementing libraries processed counter."""
        metrics = ProcessingMetrics()

        metrics.add_library_processed("Library 1")
        assert metrics.libraries_processed == 1

        metrics.add_library_processed("Library 2")
        assert metrics.libraries_processed == 2

    def test_add_series_processed_success(self):
        """Test adding successfully processed series."""
        metrics = ProcessingMetrics()

        metrics.add_series_processed("Series 1", success=True, processing_time=1.5)
        assert metrics.series_processed == 1
        assert metrics.series_successful == 1
        assert metrics.series_failed == 0
        assert metrics.average_series_processing_time == 1.5
        assert metrics.slowest_series_processing_time == 1.5
        assert metrics.slowest_series_name == "Series 1"

    def test_add_series_processed_failure(self):
        """Test adding failed series processing."""
        metrics = ProcessingMetrics()

        metrics.add_series_processed("Series 1", success=False, processing_time=2.0)
        assert metrics.series_processed == 1
        assert metrics.series_successful == 0
        assert metrics.series_failed == 1

    def test_multiple_series_processing_times(self):
        """Test calculation of average processing time with multiple series."""
        metrics = ProcessingMetrics()

        metrics.add_series_processed("Series 1", success=True, processing_time=1.0)
        assert metrics.average_series_processing_time == 1.0

        metrics.add_series_processed("Series 2", success=True, processing_time=3.0)
        assert metrics.average_series_processing_time == 2.0  # (1.0 + 3.0) / 2

        metrics.add_series_processed("Series 3", success=True, processing_time=2.0)
        assert metrics.average_series_processing_time == 2.0  # (1.0 + 3.0 + 2.0) / 3

    def test_slowest_series_tracking(self):
        """Test tracking of slowest processing series."""
        metrics = ProcessingMetrics()

        metrics.add_series_processed("Fast Series", success=True, processing_time=1.0)
        assert metrics.slowest_series_name == "Fast Series"
        assert metrics.slowest_series_processing_time == 1.0

        metrics.add_series_processed("Slow Series", success=True, processing_time=5.0)
        assert metrics.slowest_series_name == "Slow Series"
        assert metrics.slowest_series_processing_time == 5.0

        metrics.add_series_processed("Medium Series", success=True, processing_time=3.0)
        assert metrics.slowest_series_name == "Slow Series"  # Should remain the slowest
        assert metrics.slowest_series_processing_time == 5.0

    def test_add_series_skipped(self):
        """Test incrementing skipped series counter."""
        metrics = ProcessingMetrics()

        metrics.add_series_skipped("Skipped Series 1")
        assert metrics.series_skipped == 1

        metrics.add_series_skipped("Skipped Series 2")
        assert metrics.series_skipped == 2

    def test_api_call_tracking(self):
        """Test API call counting."""
        metrics = ProcessingMetrics()

        metrics.add_api_call("komga", success=True)
        assert metrics.komga_api_calls == 1
        assert metrics.komga_api_errors == 0

        metrics.add_api_call("komga", success=False)
        assert metrics.komga_api_calls == 2
        assert metrics.komga_api_errors == 1

        metrics.add_api_call("anilist", success=True)
        assert metrics.anilist_api_calls == 1
        assert metrics.anilist_api_errors == 0

    def test_cache_hit_miss_tracking(self):
        """Test cache hit/miss counting."""
        metrics = ProcessingMetrics()

        metrics.add_cache_hit("metadata")
        assert metrics.cache_hits["metadata"] == 1

        metrics.add_cache_hit("translation")
        assert metrics.cache_hits["translation"] == 1

        metrics.add_cache_miss("metadata")
        assert metrics.cache_misses["metadata"] == 1

    def test_cache_hit_ratio_calculation(self):
        """Test cache hit ratio calculations."""
        metrics = ProcessingMetrics()

        # 2 hits, 1 miss for metadata cache
        metrics.add_cache_hit("metadata")
        metrics.add_cache_hit("metadata")
        metrics.add_cache_miss("metadata")

        # 1 hit for translation cache
        metrics.add_cache_hit("translation")

        ratios = metrics.cache_hit_ratio
        assert ratios["metadata"] == pytest.approx(66.7, abs=0.1)  # 2/3
        assert ratios["translation"] == 100.0  # 1/1
        assert ratios.get("nonexistent", 0) == 0.0

    def test_metadata_update_tracking(self):
        """Test metadata field update counting."""
        metrics = ProcessingMetrics()

        metrics.add_metadata_update("summary")
        assert metrics.metadata_updates["summary"] == 1

        metrics.add_metadata_update("genres")
        assert metrics.metadata_updates["genres"] == 1

        metrics.add_metadata_update("summary")  # Second summary update
        assert metrics.metadata_updates["summary"] == 2

    def test_translation_tracking(self):
        """Test translation counting."""
        metrics = ProcessingMetrics()

        metrics.add_translation("fr", manual=False)
        assert metrics.translations_performed["fr"] == 1

        metrics.add_translation("es", manual=True)
        assert metrics.manual_translations_used["es"] == 1

        metrics.add_translation("fr", manual=False)
        assert metrics.translations_performed["fr"] == 2

    def test_error_tracking(self):
        """Test error recording."""
        metrics = ProcessingMetrics()

        metrics.add_error("network", "Connection timeout", "series1")
        assert len(metrics.errors) == 1
        assert metrics.errors[0]["type"] == "network"
        assert metrics.errors[0]["message"] == "Connection timeout"
        assert metrics.errors[0]["series_id"] == "series1"

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        metrics = ProcessingMetrics()

        # No processing yet
        assert metrics.success_rate == 100.0

        # Add successful and failed series
        metrics.add_series_processed("Series 1", success=True)
        metrics.add_series_processed("Series 2", success=True)
        metrics.add_series_processed("Series 3", success=False)

        assert metrics.success_rate == pytest.approx(66.7, abs=0.1)  # 2/3

    def test_cache_size_setting(self):
        """Test setting cache sizes."""
        metrics = ProcessingMetrics()

        metrics.set_cache_size("metadata", 150)
        assert metrics.cache_sizes["metadata"] == 150

        metrics.set_cache_size("translation", 80)
        assert metrics.cache_sizes["translation"] == 80

    def test_session_duration(self):
        """Test session duration calculation."""
        metrics = ProcessingMetrics()

        # Before completion, duration should use current time
        initial_duration = metrics.session_duration
        assert initial_duration >= 0

        time.sleep(0.1)
        metrics.mark_session_complete()

        # After completion, duration should be fixed
        final_duration = metrics.session_duration
        assert final_duration > initial_duration
        assert final_duration == metrics.session_duration  # Should not change
