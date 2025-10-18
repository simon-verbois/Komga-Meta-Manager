# -*- coding: utf-8 -*-
"""
Circuit Breaker implementation for resilient API calls.
"""
import time
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Dict, Optional
import threading

logger = logging.getLogger(__name__)

class CircuitBreakerState(Enum):
    """Enumeration of possible circuit breaker states."""
    CLOSED = "CLOSED"  # Normal operation, allowing requests
    OPEN = "OPEN"  # Circuit is open, blocking requests
    HALF_OPEN = "HALF_OPEN"  # Testing if the service has recovered

class CircuitBreakerException(Exception):
    """Exception raised when the circuit breaker is open."""
    pass

class CircuitBreakerMetrics:
    """
    Metrics collection for a specific circuit breaker instance.

    This class tracks the circuit breaker's state transitions and performance.
    """

    def __init__(self):
        self.state_changes: Dict[str, int] = {}
        self.failure_count: int = 0
        self.success_count: int = 0
        self.request_count: int = 0
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self.last_failure_time: Optional[float] = None
        self.last_state_change_time: float = time.time()

    def record_state_change(self, from_state: CircuitBreakerState, to_state: CircuitBreakerState):
        """Record a state transition."""
        key = f"{from_state.value}_TO_{to_state.value}"
        self.state_changes[key] = self.state_changes.get(key, 0) + 1
        self.last_state_change_time = time.time()

    def record_request(self, success: bool):
        """Record the outcome of a request."""
        self.request_count += 1
        if success:
            self.success_count += 1
            self.consecutive_successes += 1
            self.consecutive_failures = 0
        else:
            self.failure_count += 1
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            self.last_failure_time = time.time()

class CircuitBreakerConfig:
    """
    Configuration for a circuit breaker.

    Attributes:
        failure_threshold: Number of consecutive failures before opening the circuit
        recovery_timeout: Time in seconds to wait before trying to close the circuit
        success_threshold: Number of consecutive successes needed in HALF_OPEN state to close circuit
        name: Optional name for the circuit breaker (for logging)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 3,
        name: str = "unnamed"
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.name = name

class CircuitBreaker:
    """
    Circuit Breaker implementation to prevent cascading failures.

    The Circuit Breaker monitors requests to a service and can transition between three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service considered down, requests are blocked and fail fast
    - HALF_OPEN: Testing phase, limited requests to check if service recovered

    This implementation is thread-safe and provides comprehensive metrics.
    """

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self._state = CircuitBreakerState.CLOSED
        self._state_lock = threading.RLock()
        self.metrics = CircuitBreakerMetrics()

    @property
    def state(self) -> CircuitBreakerState:
        """Get the current state of the circuit breaker."""
        with self._state_lock:
            return self._state

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function with circuit breaker protection.

        Args:
            func: The function to call
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            The result of the function call

        Raises:
            CircuitBreakerException: If the circuit is open
            Exception: Any exception raised by the function
        """
        if not self._can_attempt_request():
            logger.warning(f"Circuit breaker '{self.config.name}' is OPEN, blocking request")
            raise CircuitBreakerException(f"Circuit breaker '{self.config.name}' is open")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _can_attempt_request(self) -> bool:
        """Check if a request should be attempted based on current state."""
        with self._state_lock:
            if self._state == CircuitBreakerState.CLOSED:
                return True
            elif self._state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                    return True
                return False
            else:  # HALF_OPEN
                return True

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self.metrics.last_failure_time is None:
            return False
        return time.time() - self.metrics.last_failure_time >= self.config.recovery_timeout

    def _on_success(self):
        """Handle a successful request."""
        with self._state_lock:
            self.metrics.record_request(success=True)

            if self._state == CircuitBreakerState.HALF_OPEN:
                if self.metrics.consecutive_successes >= self.config.success_threshold:
                    self._transition_to_closed()
            # In CLOSED state, success doesn't change state

    def _on_failure(self):
        """Handle a failed request."""
        with self._state_lock:
            self.metrics.record_request(success=False)

            if self._state == CircuitBreakerState.CLOSED:
                if self.metrics.consecutive_failures >= self.config.failure_threshold:
                    self._transition_to_open()
            elif self._state == CircuitBreakerState.HALF_OPEN:
                # Any failure in HALF_OPEN immediately goes back to OPEN
                self._transition_to_open()

    def _transition_to_closed(self):
        """Transition the circuit breaker to CLOSED state."""
        old_state = self._state
        self._state = CircuitBreakerState.CLOSED
        self.metrics.record_state_change(old_state, self._state)
        logger.info(f"Circuit breaker '{self.config.name}' transitioned from {old_state.value} to {self._state.value}")

    def _transition_to_open(self):
        """Transition the circuit breaker to OPEN state."""
        old_state = self._state
        self._state = CircuitBreakerState.OPEN
        self.metrics.record_state_change(old_state, self._state)
        logger.warning(f"Circuit breaker '{self.config.name}' transitioned from {old_state.value} to {self._state.value}")

    def _transition_to_half_open(self):
        """Transition the circuit breaker to HALF_OPEN state."""
        old_state = self._state
        self._state = CircuitBreakerState.HALF_OPEN
        self.metrics.record_state_change(old_state, self._state)
        logger.info(f"Circuit breaker '{self.config.name}' transitioned from {old_state.value} to {self._state.value}")

class CircuitBreakerFactory:
    """
    Factory for creating and managing circuit breakers.

    This factory ensures that circuit breakers are reused for the same service,
    avoiding the creation of multiple circuit breakers for the same endpoint.
    """

    def __init__(self):
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_circuit_breaker(self, config: CircuitBreakerConfig) -> CircuitBreaker:
        """
        Get or create a circuit breaker for the given configuration.

        Args:
            config: Configuration for the circuit breaker

        Returns:
            The circuit breaker instance
        """
        with self._lock:
            if config.name not in self._circuit_breakers:
                self._circuit_breakers[config.name] = CircuitBreaker(config)
                logger.debug(f"Created new circuit breaker '{config.name}'")

            return self._circuit_breakers[config.name]

    def get_all_circuit_breakers(self) -> Dict[str, CircuitBreaker]:
        """Get all active circuit breaker instances."""
        with self._lock:
            return self._circuit_breakers.copy()

# Global factory instance
circuit_breaker_factory = CircuitBreakerFactory()

def create_circuit_breaker_config(service_name: str, name_suffix: str = "") -> CircuitBreakerConfig:
    """
    Create a circuit breaker configuration from constants.

    Args:
        service_name: Name of the service (komga, anilist, translation)
        name_suffix: Optional suffix for the circuit breaker name

    Returns:
        Configured CircuitBreakerConfig instance
    """
    from modules.constants import CIRCUIT_BREAKER_DEFAULTS

    if service_name not in CIRCUIT_BREAKER_DEFAULTS:
        raise ValueError(f"Unknown service '{service_name}' for circuit breaker configuration")

    defaults = CIRCUIT_BREAKER_DEFAULTS[service_name]
    name = f"{service_name}_circuit_breaker{name_suffix}"

    return CircuitBreakerConfig(
        failure_threshold=defaults['failure_threshold'],
        recovery_timeout=defaults['recovery_timeout'],
        success_threshold=defaults['success_threshold'],
        name=name
    )
