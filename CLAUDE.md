# OpenDoor Data Platform - Project Guidelines

## Overview

This document provides guidelines for developing and maintaining the OpenDoor Healthcare Data Platform. Follow these standards to ensure code quality, maintainability, and consistency across the codebase.

## Code Style

### Python Standards

- **PEP 8**: Follow PEP 8 style guide for Python code
- **Line Length**: Maximum 88 characters (Black formatter default)
- **Imports**: Use `isort` for consistent import ordering
  ```
  # Standard library
  import os
  import sys

  # Third-party
  import pandas as pd
  from sqlalchemy import create_engine

  # Local
  from src.models import Physician
  ```

### Formatting Tools

Run before committing:
```bash
black src/ tests/
isort src/ tests/
flake8 src/ tests/
mypy src/
```

### Type Hints

- Use type hints for all function signatures
- Use Pydantic models for data validation
- Example:
  ```python
  def calculate_valuation(
      practice: Practice,
      multipliers: ValuationMultipliers
  ) -> ValuationResult:
      ...
  ```

## Testing

### Framework

- **pytest** for all tests
- Target **80%+ code coverage**

### Test Structure

```
tests/
├── unit/              # Unit tests for individual functions
├── integration/       # Integration tests for database/API
├── fixtures/          # Test data files
└── conftest.py        # Shared fixtures
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_valuation_engine.py

# Run tests matching pattern
pytest -k "valuation"
```

### Test Naming

- Use descriptive test names: `test_calculate_valuation_with_high_commercial_payer_mix`
- Group related tests in classes: `class TestValuationEngine:`

## Documentation

### Docstrings

Use Google-style docstrings:

```python
def calculate_geographic_multiplier(zip_code: str) -> float:
    """Calculate geographic multiplier based on ZIP code.

    Args:
        zip_code: 5-digit ZIP code string.

    Returns:
        Geographic multiplier between 0.7 and 1.5.

    Raises:
        ValueError: If ZIP code is invalid.

    Example:
        >>> calculate_geographic_multiplier("02101")
        1.35
    """
```

### Module Docstrings

Each module should have a docstring explaining its purpose:

```python
"""NPPES data ingestion module.

This module handles downloading, parsing, and loading National Plan and
Provider Enumeration System (NPPES) data into the data warehouse.
"""
```

## Data Handling Best Practices

### Data Validation

- Always validate incoming data using Pydantic models
- Log validation errors but don't fail silently
- Store original values when cleaning data

### Large File Handling

- Use chunked reading for large CSV files:
  ```python
  for chunk in pd.read_csv(file_path, chunksize=10000):
      process_chunk(chunk)
  ```
- Stream downloads for large files
- Use generators where possible

### Database Operations

- Use batch inserts (10,000 records per batch)
- Implement upsert logic for updates
- Always use transactions for multi-table operations
- Index commonly queried fields (NPI, ZIP code, specialty)

### Sensitive Data

- Never log PII (patient names, SSNs)
- Use environment variables for credentials
- Encrypt sensitive fields at rest

## Error Handling

### Logging

Use structured logging with `structlog`:

```python
import structlog

logger = structlog.get_logger()

logger.info("processing_physician", npi=npi, specialty=specialty)
logger.error("validation_failed", npi=npi, error=str(e))
```

### Exception Handling

- Create custom exceptions for domain-specific errors
- Always log exceptions with context
- Retry transient failures with exponential backoff

```python
class NPPESDownloadError(Exception):
    """Raised when NPPES data download fails."""
    pass

class ValidationError(Exception):
    """Raised when data validation fails."""
    pass
```

## Git Workflow

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `refactor/description` - Code refactoring

### Commit Messages

Use conventional commits:
- `feat: add payer mix multiplier calculation`
- `fix: handle missing ZIP codes in NPPES data`
- `docs: update valuation formula documentation`
- `test: add tests for geographic multiplier`

### Pull Requests

- Include description of changes
- Reference related issues
- Ensure all tests pass
- Request review from at least one team member

## Architecture Guidelines

### Module Dependencies

```
src/models/     <- No dependencies on other src modules
src/utils/      <- Only depends on models
src/ingest/     <- Depends on models, utils
src/transform/  <- Depends on models, utils, ingest
src/load/       <- Depends on models, utils
src/analytics/  <- Depends on models, utils
src/api/        <- Depends on all modules
```

### Adding New Data Sources

1. Create new module in `src/ingest/{source_name}/`
2. Implement client, parser, and loader
3. Add Pydantic models in `src/models/`
4. Add database migration in `migrations/`
5. Update pipeline in `pipelines/`
6. Add comprehensive tests

### Performance Considerations

- Profile slow operations with `cProfile`
- Use database connection pooling
- Cache expensive calculations
- Parallelize independent operations

## Common Commands

```bash
# Development
python -m pipelines.ingestion_pipeline    # Run full pipeline
python -m pipelines.update_pipeline       # Run incremental update
uvicorn src.api.main:app --reload         # Start API server

# Database
alembic upgrade head                       # Run migrations
alembic revision --autogenerate -m "msg"  # Create migration

# Quality
black src/ tests/                         # Format code
isort src/ tests/                         # Sort imports
flake8 src/ tests/                        # Lint code
mypy src/                                  # Type check
pytest --cov=src                          # Run tests with coverage
```
