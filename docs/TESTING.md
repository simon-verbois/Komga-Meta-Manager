# Testing Guide - Komga Meta Manager

## 🎯 Overview

The project uses `pytest` for unit and integration tests. Tests validate:

- Business logic (fuzzy matching, configuration validation)
- External interfaces (API mocks)
- Resilience (error tests, edge cases)
- Performance (benchmarks for critical operations)

## 📁 Structure

```
tests/
├── __init__.py              # Mark as Python package
├── conftest.py             # Shared fixtures and configuration
├── pytest.ini             # Pytest configuration
├── test_processor.py      # Processing logic tests
├── test_metrics.py        # Metrics tests
└── test_*.py              # Tests to implement (TODO)
```

## 🚀 Running

### Basic Commands

```bash
# All tests
pytest

# Verbose tests with details
pytest -v

# Tests with coverage report
pytest --cov=modules --cov-report=html
pytest --cov=modules --cov-report=term-missing

# Specific module tests
pytest tests/test_metrics.py

# Specific class tests
pytest tests/test_metrics.py::TestProcessingMetrics

# Specific method tests
pytest tests/test_processor.py::TestChooseBestMatch::test_exact_match_returns_best_candidate
```

### Filters and Markers

```bash
# Run only fast unit tests
pytest -m "unit and not slow"

# Run only integration tests
pytest -m integration

# Run slow tests (marked with @pytest.mark.slow)
pytest -m slow

# Tests that don't require internet
pytest -m "not integration"

# Performance tests
pytest -m perf
```

### Advanced Options

```bash
# Parallel execution (requires pytest-xdist)
pytest -n auto

# Debug mode (stop on first error)
pytest --pdb

# XML report for CI
pytest --junitxml=reports/junit.xml

# Performance profiling
pytest --durations=10
```

## 🛠️ Writing Tests

### Typical Test Structure

```python
import pytest
from unittest.mock import Mock, patch
from modules.my_module import MyClass, my_function

class TestMyClass:
    """Tests for MyClass."""

    def setup_method(self):
        """Setup before each test."""
        self.instance = MyClass()

    def test_success_case(self):
        """Test the happy path."""
        # Given
        config = Mock()
        config.value = "test"

        # When
        result = self.instance.process(config)

        # Then
        assert result.success is True
        assert result.data == "expected"

    def test_error_case(self):
        """Test error case."""
        # Given
        config = Mock()
        config.invalid_param = True

        # When/Then
        with pytest.raises(ValueError, match="Invalid parameter"):
            self.instance.process(config)

    @pytest.mark.parametrize("input,expected", [
        ("hello", "HELLO"),
        ("world", "WORLD"),
        ("123", "123"),
    ])
    def test_parametrized(self, input, expected):
        """Parameterized test for multiple cases."""
        result = my_function(input)
        assert result == expected

    @pytest.mark.slow
    def test_slow_operation(self):
        """Test that takes time (marked as slow)."""
        result = self.instance.heavy_computation()
        assert result.is_valid()
```

### Available Fixtures

See `conftest.py` for predefined fixtures:

- `temp_dir`: Temporary directory
- `mock_komga_config`: Mocked Komga configuration
- `mock_anilist_response`: Mocked AniList JSON response
- `mock_requests_session`: Mocked HTTP session
- `mock_googletrans_translator`: Mocked Google translator

### Best Practices

1. **Clear naming**: `test_should_return_empty_when_input_invalid`
2. **Single concept per test**: Avoid tests that do too many things
3. **Mock external calls**: Mock APIs, filesystem, and external dependencies
4. **Cover edge cases**: Test bounds, None values, empty strings, etc.
5. **Descriptive assertions**: Use clear assertion messages
6. **Setup/Teardown**: Use fixtures for repetition

### Error Cases Tests

```python
def test_timeout_handling(self, mock_requests_session):
    """Test that timeouts are handled correctly."""
    # Configure mock to raise Timeout
    mock_requests_session.get.side_effect = requests.Timeout("Request timed out")

    client = KomgaClient(Mock())

    with pytest.raises(TimeoutError):
        client.get_libraries()
```

### Performance Tests

```python
@pytest.mark.perf
def test_processing_performance(self, benchmark):
    """Performance test for critical operation."""
    processor = Processor()

    # Benchmark automatically returns metrics
    result = benchmark(processor.process_large_dataset)

    assert result is not None
    # Benchmark automatically provides timings, memory usage, etc.
```

## 🔍 Test Debugging

### Test Failure

```bash
# See failure details
pytest -v --tb=long

# Interactive debug on failure
pytest --pdb --tb=short
```

### Creating Reproducing Test

```python
def test_reproduce_bug_123(self):
    """Test reproducing bug #123.

    Bug description:
    When calling method() with arg=None,
    AttributeError is obtained.

    Steps to reproduce:
    1. Create instance
    2. Call method(None)
    3. Verify AttributeError is raised
    """
    instance = MyClass()

    with pytest.raises(AttributeError):
        instance.method(None)
```

## 📊 Quality Metrics

### Coverage Target: >80%

```bash
# Generate HTML coverage report
pytest --cov=modules --cov-report=html
# Open htmlcov/index.html in browser
```

### Important Metrics

- **Line coverage**: Percentage of executed lines
- **Branch coverage**: Covered if/else conditions
- **Cyclomatic complexity**: Code maintainability

### CI/CD Integration

```yaml
# GitHub Actions example
- name: Run tests
  run: |
    pip install -r requirements.txt
    pip install pytest pytest-cov
    pytest --cov=modules --cov-report=xml
```

## 🐛 Common Problems and Solutions

### Problem: Slow tests

**Solutions:**
- Mark with `@pytest.mark.slow`
- Mock slow calls
- Run in parallel with `pytest-xdist`

### Problem: Tests depend on external services

**Solutions:**
- Mock all external APIs
- Use `responses` to mock HTTP
- Create static data fixtures

### Problem: Flaky tests (intermittent failures)

**Solutions:**
- Avoid sleeps and timeouts
- Use deterministic mocks
- Configure appropriate timeouts

### Problem: Tests don't cover enough

**Solutions:**
- Use `coverage.py` directly
- Analyze uncovered branches
- Add tests for exceptions

## 📋 Pre-commit Checklist

- [ ] All tests pass: `pytest`
- [ ] Coverage > 80%: `pytest --cov=manga_manager --cov-report=term-missing`
- [ ] No regressions: Test critical scenarios
- [ ] Lint OK: `flake8 --max-line-length=100 manga_manager/`
- [ ] Code formatted: `black manga_manager/`

## 🔄 Test Maintenance

### Dead Code Removal

When removing production code, also remove its tests.

### Refactoring

When renaming a function/class:
1. Rename corresponding test
2. Update all calls in tests

### New Features

For each new feature:
1. Write tests first (TDD)
2. Implement feature
3. Verify coverage

This approach ensures code stays testable and maintainable.
