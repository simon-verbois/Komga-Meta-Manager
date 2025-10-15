# Development Guide - Komga Meta Manager

## 🏗️ Architecture

The project follows a modular architecture with clear separation of responsibilities:

```
src/manga_manager/
├── constants.py          # Centralized constants
├── config.py             # Configuration and validation
├── main.py               # Main entry point
├── metrics.py            # Metrics collection
├── models.py             # Pydantic data models
├── komga_client.py       # Client for Komga API
├── processor.py          # Main processing logic
├── providers/            # Metadata providers
│   ├── base.py          # Common interface
│   └── anilist_provider.py  # AniList implementation
└── translators/          # Translators
    ├── base.py          # Common interface
    ├── google_translator.py  # Google Translate implementation
    └── deepl_translator.py   # DeepL implementation
```

## 🧪 Tests

### Test Structure

Tests are organized in the `tests/` folder:

```
tests/
├── __init__.py
├── conftest.py           # Fixtures and configuration
├── pytest.ini           # Pytest configuration
├── test_processor.py    # Processing logic tests
├── test_metrics.py      # Metrics tests
└── test_config.py       # Configuration validation tests (TODO)
```

### Running Tests

```bash
# All tests
pytest

# Specific tests
pytest tests/test_processor.py

# With coverage
pytest --cov=manga_manager --cov-report=html

# Slow tests only
pytest -m slow

# Unit tests only (default)
pytest -m unit
```

### Writing Tests

#### Principles
- Use `pytest` as testing framework
- Organize tests in classes with descriptive names
- Use fixtures for common configuration
- Mock external calls (APIs, filesystem)
- Test error cases as well as happy paths

#### Test Example

```python
import pytest
from unittest.mock import Mock

def test_example():
    # Arrange
    component = Component()
    config = Mock()

    # Act
    result = component.process(config)

    # Assert
    assert result.success is True
    assert result.data is not None
```

## 🔧 Development

### Environment

1. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

3. Install in development mode:
```bash
pip install -e .
```

### Pre-commit hooks

To maintain code quality:

```bash
pip install pre-commit
pre-commit install
```

Hooks verify:
- Code formatting (black)
- Import sorting (isort)
- Linting (flake8)
- Automated tests

### Debugging

#### Debug mode

Enable debug mode in configuration:

```yaml
system:
  debug: true
```

#### Detailed logs

Add temporary logs:

```python
import logging
logger = logging.getLogger(__name__)
logger.debug(f"Processing: {variable}")
```

#### Breakpoints

Use `pdb` for interactive debugging:

```python
import pdb; pdb.set_trace()
```

## 🚀 Deployment

### Docker

The project uses Docker for production:

```bash
# Build
docker build -t komga-meta-manager .

# Run
docker run --rm komga-meta-manager
```

### Local Development

To test locally:

```bash
# Dry-run mode
python -m manga_manager.main

# With custom configuration
python -m manga_manager.main --config /path/to/config.yml
```

## 📋 Best Practices

### Code

- **Type hints**: Always use type annotations
- **Docstrings**: Document all public functions
- **PEP 8**: Respect Python style conventions
- **Fail fast**: Check preconditions at function start

### Error Handling

- **Specific exceptions**: Create custom exceptions when needed
- **Clear messages**: Provide informative error messages
- **Logging**: Log errors with context
- **Recovery**: Implement recovery strategies when possible

### Performance

- **Cache**: Use cache to avoid repeated calls
- **Metrics**: Profile bottlenecks with metrics
- **Async**: Consider asyncio for massive I/O operations (future)

## 🤝 Contribution

### Workflow

1. Create a feature branch: `git checkout -b feature/feature-name`
2. Write tests for the new functionality
3. Implement the functionality
4. Verify all tests pass
5. Submit PR with detailed description

### Commit Conventions

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `test`: Tests
- `refactor`: Refactoring without functional changes
- `perf`: Performance improvement
- `chore`: Maintenance

### Reviews

- All PRs must be reviewed
- Tests must pass on CI
- Coverage must be maintained > 80%

## 📊 Monitoring

### Key Metrics

- Average processing time per series
- API call success rate
- Cache hit rates
- Error count by type

### Alerts

- API failure rate > 10%
- Processing time > 2x average
- Cache hit rate < 50%

See `metrics.py` for complete implementation.
