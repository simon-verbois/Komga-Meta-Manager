# Development Guide - Komga Meta Manager

## 🏗️ Architecture

The project follows a modular architecture with clear separation of responsibilities:

```
modules/
├── constants.py          # Centralized constants
├── config.py             # Configuration and validation
├── main.py               # Main entry point
├── metrics.py            # Metrics collection
├── models.py             # Pydantic data models
├── komga_client.py       # Client for Komga API
├── processor.py          # Main processing logic
├── providers/            # Metadata providers
│   ├── __init__.py      # Factory functions
│   ├── base.py          # Common interface
│   └── anilist.py       # AniList implementation
└── translators/          # Translators
    ├── __init__.py      # Factory functions
    ├── base.py          # Common interface
    ├── google.py        # Google Translate implementation
    └── deepl.py         # DeepL implementation
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

Tests run exclusively in a Docker container via `testing-compose.yml`:

```bash
# Build and run all tests
docker compose -f testing-compose.yml up --build

# For quick code modifications, after initial build:
docker compose -f testing-compose.yml up --no-build
```

The testing container automatically executes pytest with the following commands:
- Complete tests with coverage
- Stop on first error and exit with error code if failed

#### Test filtering (not available directly, modify compose if needed)

```bash
# To filter: Modify testing-compose.yml to add pytest arguments
pytest tests/test_processor.py  # Specific tests
pytest -m slow                 # Slow tests only
pytest --cov-report=html       # HTML coverage
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

**Important:** Komga Meta Manager runs exclusively in Docker containers. No local development or execution is supported.

### Docker Development

All development activities use the provided Docker infrastructure:

#### Development configuration

1. **Build and tests:** Use the provided `testing-compose.yml` to run tests in a container:
```bash
docker compose -f testing-compose.yml up --build
```

2. **Manual execution:** To quickly test changes:
```bash
docker compose -f compose.yml run --rm komga-meta-manager
```

3. **Debug mode:** Enable detailed logs in your configuration:
```yaml
system:
  debug: true
```

#### Development structure

```
Komga-Meta-Manager/
├── modules/        # Python source code
├── tests/          # Unit/integration tests
├── config/         # Configuration and templates
├── compose.yml     # Production Docker
├── testing-compose.yml # Development Docker
└── Dockerfile      # Base image
```

## 🚀 Deployment

### Docker Production

The deployment is done exclusively via Docker:

```bash
# Production
docker compose up -d

# Single execution
docker compose run --rm komga-meta-manager
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
