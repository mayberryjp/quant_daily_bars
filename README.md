# quant_daily_bars

Daily OHLCV bar ingestion service for the quant momentum pipeline.

## Local Infrastructure

Requirements:

- Docker with Docker Compose v2
- Python 3.12

Bootstrap:

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
docker compose up -d postgres   # if using shared quant_symbols postgres
alembic upgrade head
python3 -m quant_daily_bars.cli db verify
```

## Database Schema

The migration creates the `market_data` schema with these tables:

| Table | Purpose |
|-------|---------|
| `market_data.vendor_bar_sources` | Registered bar data vendors (seeded with `polygon`) |
| `market_data.vendor_bar_runs` | Per-run tracking for ingestion jobs (mode, dates, counts, duration) |
| `market_data.daily_bars` | OHLCV bars keyed by `(symbol_id, bar_date, adjustment_type)` |
| `market_data.corporate_actions` | Splits, dividends, symbol changes (placeholder for future use) |
| `market_data.missing_bars` | Bars expected but not returned, for operator inspection |

Apply migrations:

```bash
python3 -m quant_daily_bars.cli db upgrade
python3 -m quant_daily_bars.cli db verify
```

### Adjusted vs Unadjusted Handling

The `daily_bars` table stores an `adjustment_type` column per row:

- **`unadjusted`** (default): Raw exchange prices as reported by the vendor. These
  never change retroactively unless the vendor corrects an error.
- **`split_adjusted`**: Prices adjusted for stock splits only. These change whenever
  a new split occurs, so a full re-backfill is needed after a split event.

Both types can coexist in the same table. Downstream consumers choose the series
they need via the `adjustment_type` filter. Dividend-adjusted series are not
stored because they change daily and are better computed on-the-fly.

### Data Lineage

Every `daily_bars` row links to:

- `vendor_source_id` → identifies which vendor provided the data
- `vendor_bar_run_id` → identifies the specific ingestion run
- `fetched_at` → timestamp when the data was fetched from the vendor

The `vendor_bar_runs` table records the request window, mode, symbol counts,
and duration for each ingestion job.

### Symbol Identity

`daily_bars.symbol_id` is a logical foreign key to `symbol_master.symbols.id`
from the `quant_symbols` service. When databases are separate, this is enforced
at the application level. The `ticker` column is denormalized for query
convenience but `symbol_id` is the stable identity—tickers can change due to
corporate actions while `symbol_id` remains constant.

## CLI Usage

### Backfill (historical)

```bash
# Dry-run with fixture data (no API key or DB needed)
python3 -m quant_daily_bars.cli bars ingest \
    --from-date 2024-01-01 --to-date 2024-01-05 \
    --fixture tests/fixtures/polygon --dry-run

# Live backfill for specific tickers
MASSIVE_API_KEY=... python3 -m quant_daily_bars.cli bars ingest \
    --from-date 2024-01-01 --to-date 2024-06-01 \
    --tickers AAPL,MSFT --mode backfill

# Live backfill for all active symbols in symbol_master
MASSIVE_API_KEY=... python3 -m quant_daily_bars.cli bars ingest \
    --from-date 2024-01-01 --to-date 2024-06-01
```

### Incremental (daily refresh)

```bash
MASSIVE_API_KEY=... python3 -m quant_daily_bars.cli bars ingest \
    --from-date 2024-06-08 --mode incremental
```

### Scheduled (continuous)

```bash
MASSIVE_API_KEY=... python3 -m quant_daily_bars.cli bars ingest \
    --from-date 2024-06-08 --mode incremental --schedule 86400
```

### Run summary

```bash
python3 -m quant_daily_bars.cli bars run-summary --latest
```

## Idempotency

Re-running the same ingest window does not duplicate rows. The `daily_bars`
table has a unique constraint on `(symbol_id, bar_date, adjustment_type)` and
uses `INSERT ... ON CONFLICT DO UPDATE` so repeated runs overwrite with the
latest vendor data.

## Error Isolation

Failures for one symbol do not corrupt the whole job run. Each symbol is
ingested independently; failures are counted and reported in the job summary
while remaining symbols continue.

## Manual Verification

Small backfill and repeat run:

```bash
python3 -m quant_daily_bars.cli db upgrade
python3 -m quant_daily_bars.cli bars ingest \
    --from-date 2024-01-01 --to-date 2024-01-05 \
    --fixture tests/fixtures/polygon
python3 -m quant_daily_bars.cli bars run-summary --latest

# Repeat run — bars_upserted should be identical, no duplicates
python3 -m quant_daily_bars.cli bars ingest \
    --from-date 2024-01-01 --to-date 2024-01-05 \
    --fixture tests/fixtures/polygon
python3 -m quant_daily_bars.cli bars run-summary --latest
```

## Vendor Assumptions

- **Polygon.io** is the primary vendor via `/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}`.
- The free tier is rate-limited to 5 requests/minute. The client uses configurable
  `MASSIVE_PAGE_DELAY_SECONDS` (default 12s) and exponential backoff on 429s.
- Bar timestamps are millisecond Unix epochs in UTC. The client converts them to
  `date` objects for the `bar_date` column.

## Docker

```bash
docker build -t quant-daily-bars:dev .
docker run --rm quant-daily-bars:dev python3 --version
docker run --rm quant-daily-bars:dev python3 -m pytest -q
```

## Tests

```bash
python3 -m pytest -q
```

Tests cover model parsing, client retry/pagination, fixture ingestion, CLI
parsing, and idempotent upsert SQL structure. No API key or database required.
