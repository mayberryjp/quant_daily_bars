# Copilot Instructions — quant_daily_bars

## Build & Test

```bash
# Install (editable with dev deps)
pip install -e ".[dev]"

# Run all tests (no DB or API key needed)
python -m pytest -q

# Run a single test file or class
python -m pytest tests/test_client.py -q
python -m pytest tests/test_ingest.py::TestFixtureDryRun -q

# Run a single test by name
python -m pytest -k "test_single_fixture_dry_run" -q

# Dry-run ingestion with fixtures (no external deps)
python -m quant_daily_bars.cli bars ingest \
    --from-date 2024-01-01 --to-date 2024-01-05 \
    --fixture tests/fixtures/polygon --dry-run
```

No linter is configured in the project.

## Architecture

This is a **daily OHLCV bar ingestion service** in the `quant` momentum pipeline. It pulls market data from Polygon.io and upserts it into a PostgreSQL `market_data` schema.

### Layered design

```
CLI (_cli_impl.py)
 └─ IngestJob (ingest/job.py)        ← orchestrates a run, writes DB
     └─ PolygonBarsClient (vendors/polygon/client.py)  ← HTTP-only, no DB
         └─ Transport (vendors/polygon/transport.py)    ← urllib abstraction
```

- **Vendor layer** (`src/quant_daily_bars/vendors/polygon/`) handles HTTP, pagination, retry/backoff, and returns typed dataclasses. It never touches the database.
- **Ingest layer** (`src/quant_daily_bars/ingest/`) receives typed bars from the vendor layer and performs idempotent `INSERT ... ON CONFLICT DO UPDATE` upserts.
- **CLI layer** wires configuration, scheduling, and error reporting.

### Cross-service dependency

`daily_bars.symbol_id` references `symbol_master.symbols.id` from the **quant_symbols** service. When DBs are separate, this FK is enforced at the application level only.

## Key Conventions

- **Frozen dataclasses** for all domain models (`AggregateBar`, `AggregatesPage`, `IngestOptions`, `IngestTarget`). Mutability lives in the job orchestrator, not in data objects.
- **`from_payload` classmethods** parse raw JSON dicts into typed models with validation; keep parsing logic inside the model, not in the client.
- **Structured error hierarchy**: all vendor errors inherit from `PolygonError`. HTTP errors carry `status_code`; rate-limit errors carry `retry_after_seconds`.
- **Transport protocol**: `vendors/polygon/transport.py` defines a `Protocol` so tests can inject a fake transport without mocking `urllib`.
- **Environment configuration**: all secrets/settings come from env vars (see `.env.example`). The API key env var is `MASSIVE_API_KEY`.
- **Idempotent upserts**: the unique constraint is `(symbol_id, bar_date, adjustment_type)`. Re-running the same window overwrites with latest data.
- **Error isolation**: one symbol's failure does not abort the run. Failures are counted and reported in the summary.
- **Alembic migrations** live in `alembic/versions/`. The schema is `market_data` with a custom version table `market_data.alembic_version_daily_bars`.
- **No ORM models**: SQL is written as raw `text()` statements via SQLAlchemy Core, not mapped ORM classes.
