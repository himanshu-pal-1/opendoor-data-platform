# OpenDoor Healthcare Data Platform

A comprehensive data aggregation and analytics platform for healthcare practice valuation and the Practice Knowledge Graph.

## Overview

The OpenDoor Data Platform powers our valuation engine and Practice Knowledge Graph by aggregating, transforming, and analyzing healthcare provider data from multiple authoritative sources.

### Purpose

- **Practice Valuation Engine**: Calculate fair market valuations for healthcare practices based on revenue, payer mix, geography, and specialty
- **Practice Knowledge Graph**: Build comprehensive profiles of physicians and practices for acquisition targeting
- **Market Analytics**: Segment physicians and identify acquisition opportunities

## Data Sources

| Source | Description | Update Frequency |
|--------|-------------|------------------|
| **NPPES** | National Plan and Provider Enumeration System - NPI registry with physician demographics | Weekly |
| **PECOS** | Provider Enrollment, Chain, and Ownership System - Medicare enrollment data | Monthly |
| **CMS Payments** | Medicare physician payment and utilization data | Annually |
| **Payer Data** | Commercial and Medicaid payer mix information | Quarterly |
| **Practice Financials** | Revenue, EBITDA, and operational metrics | As available |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                              │
│  NPPES │ PECOS │ CMS Payments │ Payer Data │ Practice Financials │
└────────┬────────┬───────────────┬────────────┬──────────────────┘
         │        │               │            │
         ▼        ▼               ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      INGESTION LAYER                             │
│              (Download, Parse, Validate)                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    TRANSFORMATION LAYER                          │
│        (Clean, Normalize, Enrich, Calculate Valuations)          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DATA WAREHOUSE                              │
│                      (PostgreSQL)                                │
│   Physicians │ Practices │ Payers │ Valuations │ Analytics      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       API LAYER                                  │
│                  (FastAPI REST API)                              │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
opendoor-data-platform/
├── src/
│   ├── ingest/              # Data ingestion modules
│   │   ├── cms/             # CMS physician payment data
│   │   ├── nppes/           # Provider enumeration
│   │   ├── pecos/           # Provider enrollment
│   │   ├── payer/           # Payer mix data
│   │   └── practice/        # Practice financials
│   ├── transform/           # Data transformation
│   ├── load/                # Data warehouse loading
│   ├── models/              # Pydantic data models
│   ├── utils/               # Shared utilities
│   ├── analytics/           # Analytics and reporting
│   └── api/                 # REST API
├── pipelines/               # Orchestration workflows
├── migrations/              # Database migrations
├── tests/                   # Test suite
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
└── CLAUDE.md                # Project guidelines
```

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Docker (optional, for containerized deployment)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/opendoor-healthcare/opendoor-data-platform.git
   cd opendoor-data-platform
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. Initialize the database:
   ```bash
   python -m migrations.init_db
   ```

### Running the Pipeline

```bash
# Run full data ingestion pipeline
python -m pipelines.ingestion_pipeline

# Run incremental updates
python -m pipelines.update_pipeline
```

### Running the API

```bash
# Start the FastAPI server
uvicorn src.api.main:app --reload
```

API documentation available at: `http://localhost:8000/docs`

## Valuation Formula

The practice valuation is calculated using:

```
Base Value = Avg Revenue/Patient × Patient Panel × Payer Mix Multiplier × Geographic Multiplier × Specialty Multiplier
```

### Multipliers

| Factor | Range | Description |
|--------|-------|-------------|
| **Payer Mix** | 0.7x - 1.3x | Commercial heavy (>50%): 1.3x, Medicare: 1.0x, Medicaid: 0.7x |
| **Geographic** | 0.7x - 1.5x | High-cost markets (CA, NY, MA): 1.2-1.5x |
| **Specialty** | 0.8x - 1.8x | Cardiology: 1.5-1.8x, Primary Care: 0.9-1.0x |

## Physician Segmentation

The platform segments physicians into acquisition target categories:

- **Type 1**: Solo owners 55+, declining revenue (highest priority)
- **Type 2**: Group practice members (partnership opportunities)
- **Type 3**: Health system employed (strategic acquisitions)
- **Type 4**: Fresh graduates with debt (recruitment targets)

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html
```

## Development

See [CLAUDE.md](CLAUDE.md) for development guidelines and code standards.

## License

Proprietary - OpenDoor Healthcare Inc.
