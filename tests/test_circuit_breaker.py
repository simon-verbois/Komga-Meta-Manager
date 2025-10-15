# -*- coding: utf-8 -*-
"""
Unit tests for circuit breaker functionality.
"""
import time
import pytest
from unittest.mock import Mock, patch

from modules.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
    CircuitBreakerException,
    CircuitBreakerMetrics,
    circuit_breaker_factory
)


class TestCircuitBreakerConfig:
    """Test the circuit breaker configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60
        assert config.success_threshold == 3
        assert config.name == "unnamed"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=30,
            success_threshold=2,
            name="test_circuit"
        )
        assert config.failure_threshold == 3
        assert config.recovery_timeout == 30
        assert config.success_threshold == 2
        assert config.name == "test_circuit"


class TestCircuitBreakerMetrics:
    """Test the circuit breaker metrics collection."""

    def test_initial_metrics(self):
        """Test that metrics are initialized correctly."""
        metrics = CircuitBreakerMetrics()
        assert metrics.failure_count == 0
        assert metrics.success_count == 0
        assert metrics.request_count == 0
        assert metrics.consecutive_failures == 0
        assert metrics.consecutive_successes == 0
        assert metrics.state_changes == {}
        assert metrics.last_failure_time is None

    def test_record_request_success(self):
        """Test recording successful requests."""
        metrics = CircuitBreakerMetrics()

        # First success
        metrics.record_request(success=True)
        assert metrics.success_count == 1
        assert metrics.request_count == 1
        assert metrics.consecutive_successes == 1
        assert metrics.consecutive_failures == 0

        # Second success
        metrics.record_request(success=True)
        assert metrics.success_count == 2
        assert metrics.consecutive_successes == 2

    def test_record_request_failure(self):
        """Test recording failed requests."""
        metrics = CircuitBreakerMetrics()

        # First failure
        metrics.record_request(success=False)
        assert metrics.failure_count == 1
        assert metrics.request_count == 1
        assert metrics.consecutive_failures == 1
        assert metrics.consecutive_successes == 0
        assert metrics.last_failure_time is not None

        # Second failure
        metrics.record_request(success=False)
        assert metrics.failure_count == 2
        assert metrics.consecutive_failures == 2

    def test_record_state_change(self):
        """Test recording state transitions."""
        metrics = CircuitBreakerMetrics()

        metrics.record_state_change(CircuitBreakerState.CLOSED, CircuitBreakerState.OPEN)
        assert "CLOSED_TO_OPEN" in metrics.state_changes
        assert metrics.state_changes["CLOSED_TO_OPEN"] == 1

        metrics.record_state_change(CircuitBreakerState.OPEN, CircuitBreakerState.HALF_OPEN)
        assert metrics.state_changes["OPEN_TO_HALF_OPEN"] == 1


class TestCircuitBreaker:
    """Test the main circuit breaker functionality."""

    def test_initial_state(self):
        """Test that circuit breaker starts in CLOSED state."""
        config = CircuitBreakerConfig()
        cb = CircuitBreaker(config)
        assert cb.state == CircuitBreakerState.CLOSED

    def test_successful_requests(self):
        """Test successful requests don't change state from CLOSED."""
        config = CircuitBreakerConfig()
        cb = CircuitBreaker(config)

        def successful_func():
            return "success"

        # Multiple successful calls
        for _ in range(10):
            result = cb.call(successful_func)
            assert result == "success"

        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.metrics.success_count == 10
        assert cb.metrics.consecutive_successes == 10

    def test_failure_threshold_opens_circuit(self):
        """Test that enough failures open the circuit."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(config)

        def failing_func():
            raise Exception("Test failure")

        # Cause failures up to threshold
        for i in range(3):
            with pytest.raises(Exception):
                cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN
        assert cb.metrics.consecutive_failures == 3

    def test_open_circuit_blocks_requests(self):
        """Test that OPEN circuit blocks requests."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker(config)

        def failing_func():
            raise Exception("Test failure")

        # Open the circuit
        with pytest.raises(Exception):
            cb.call(failing_func)

        # Now circuit should be open
        assert cb.state == CircuitBreakerState.OPEN

        # Subsequent calls should fail with CircuitBreakerException
        with pytest.raises(CircuitBreakerException):
            cb.call(lambda: "success")

    def test_recovery_timeout_half_open(self):
        """Test that after recovery timeout, circuit goes to HALF_OPEN."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1  # Very short timeout for testing
        )
        cb = CircuitBreaker(config)

        def failing_func():
            raise Exception("Test failure")

        # Open the circuit
        with pytest.raises(Exception):
            cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN

        # Wait for recovery timeout
        time.sleep(0.2)

        # Next call should transition to HALF_OPEN and attempt the call
        def successful_func():
            return "success"

        result = cb.call(successful_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED  # Should close after success

    def test_half_open_success_closes_circuit(self):
        """Test that successful calls in HALF_OPEN state eventually close the circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            success_threshold=2
        )
        cb = CircuitBreaker(config)

        def failing_func():
            raise Exception("Test failure")

        # Open the circuit
        with pytest.raises(Exception):
            cb.call(failing_func)
        assert cb.state == CircuitBreakerState.OPEN

        # Wait for recovery
        time.sleep(0.2)

        # Two successful calls should close the circuit
        for _ in range(2):
            result = cb.call(lambda: "success")
            assert result == "success"

        assert cb.state == CircuitBreakerState.CLOSED

    def test_half_open_failure_keeps_open(self):
        """Test that failure in HALF_OPEN state keeps circuit open."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            success_threshold=2
        )
        cb = CircuitBreaker(config)

        def failing_func():
            raise Exception("Test failure")

        # Open the circuit
        with pytest.raises(Exception):
            cb.call(failing_func)
        assert cb.state == CircuitBreakerState.OPEN

        # Wait for recovery
        time.sleep(0.2)

        # Circuit should attempt call (transition to HALF_OPEN) but fail
        with pytest.raises(Exception):
            cb.call(failing_func)

        # Should stay open
        assert cb.state == CircuitBreakerState.OPEN

    @patch('time.time')
    def test_half_open_timing(self, mock_time):
        """Test the timing logic for transitioning to HALF_OPEN."""
        mock_time.return_value = 1000
        config = CircuitBreakerConfig(recovery_timeout=60)
        cb = CircuitBreaker(config)

        # Manually set circuit to open and record failure time
        cb._transition_to_open()
        cb.metrics.last_failure_time = 1000

        # Just after failure - should not allow request
        mock_time.return_value = 1001
        assert not cb._can_attempt_request()

        # After recovery timeout - should allow request
        mock_time.return_value = 1061
        assert cb._can_attempt_request()


class TestCircuitBreakerFactory:
    """Test the circuit breaker factory."""

    def test_get_circuit_breaker_creates_new(self):
        """Test creating a new circuit breaker."""
        factory = circuit_breaker_factory
        config = CircuitBreakerConfig(name="test")

        cb1 = factory.get_circuit_breaker(config)
        assert isinstance(cb1, CircuitBreaker)
        assert cb1.config.name == "test"

    def test_get_circuit_breaker_reuses_existing(self):
        """Test that same config returns the same instance."""
        factory = circuit_breaker_factory
        config = CircuitBreakerConfig(name="reuse_test")

        cb1 = factory.get_circuit_breaker(config)
        cb2 = factory.get_circuit_breaker(config)

        assert cb1 is cb2

    def test_get_all_circuit_breakers(self):
        """Test getting all circuit breakers."""
        factory = circuit_breaker_factory
        config1 = CircuitBreakerConfig(name="cb1")
        config2 = CircuitBreakerConfig(name="cb2")

        cb1 = factory.get_circuit_breaker(config1)
        cb2 = factory.get_circuit_breaker(config2)

        all_cbs = factory.get_all_circuit_breakers()
        assert "cb1" in all_cbs
        assert "cb2" in all_cbs
        assert all_cbs["cb1"] is cb1
        assert all_cbs["cb2"] is cb2


class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with real functions."""

    def test_with_external_function(self):
        """Test circuit breaker with an external function that can succeed/fail."""
        call_count = [0]  # Use list to modify in nested function

        def external_service(success_after=None):
            call_count[0] += 1
            if success_after and call_count[0] >= success_after:
                return "success"
            raise Exception("Service unavailable")

        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        cb = CircuitBreaker(config)

        # Fail twice to open circuit
        for _ in range(2):
            with pytest.raises(Exception):
                cb.call(external_service)

        assert cb.state == CircuitBreakerState.OPEN

        # Should be blocked
        with pytest.raises(CircuitBreakerException):
            cb.call(external_service)

        # Wait for recovery and configure service to succeed
        time.sleep(0.2)
        result = cb.call(lambda: external_service(success_after=3))
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED
