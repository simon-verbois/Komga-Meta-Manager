import json
import time

import pytest

from modules.cache import Cache
from modules.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerException,
    CircuitBreakerFactory,
    CircuitBreakerState,
    create_circuit_breaker_config,
)


def test_cache_round_trip_expiry_and_atomic_save(tmp_path) -> None:
    cache = Cache("cache.json", tmp_path, ttl_hours=1)
    cache.set("key", {"value": 1})
    assert cache.get("key") == {"value": 1}
    cache.save_to_disk()
    assert not (tmp_path / "cache.json.tmp").exists()

    loaded = Cache("cache.json", tmp_path, ttl_hours=1)
    assert loaded.get("key") == {"value": 1}
    loaded.cache["key"]["timestamp"] = time.time() - 7200
    assert loaded.get("key") is None


def test_corrupt_and_wrong_version_caches_are_ignored(tmp_path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("not-json", encoding="utf-8")
    assert Cache("cache.json", tmp_path, 1).cache == {}

    path.write_text(json.dumps({"__version__": "other", "key": {}}), encoding="utf-8")
    assert Cache("cache.json", tmp_path, 1).cache == {}


def test_circuit_breaker_opens_blocks_and_recovers() -> None:
    breaker = CircuitBreaker(
        CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0, success_threshold=1, name="service")
    )
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("failed")))
    assert breaker.state is CircuitBreakerState.OPEN
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state is CircuitBreakerState.CLOSED


def test_open_circuit_blocks_before_timeout() -> None:
    breaker = CircuitBreaker(
        CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60, name="service")
    )
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("failed")))
    with pytest.raises(CircuitBreakerException):
        breaker.call(lambda: "never")


def test_circuit_factory_reuses_names_and_validates_services() -> None:
    factory = CircuitBreakerFactory()
    config = CircuitBreakerConfig(name="shared")
    assert factory.get_circuit_breaker(config) is factory.get_circuit_breaker(config)
    assert "shared" in factory.get_all_circuit_breakers()
    assert create_circuit_breaker_config("komga").name == "komga_circuit_breaker"
    with pytest.raises(ValueError):
        create_circuit_breaker_config("unknown")

