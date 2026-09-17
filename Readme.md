# Udyam MSME Extractor

**Version 3.1.0**

Production-grade Python pipeline for extracting MSME registered-unit data from the Government of India's Udyam dataset via the `data.gov.in` API. Designed for Supplier.io's supplier intelligence ingestion workflow.

---

## What It Does

Retrieves all 43M+ MSME records from the Udyam portal, processing one Indian state at a time, with parallel state workers. Each API page (10,000 records) is atomically persisted as an individual CSV artifact. Completed batches are published directly to Amazon S3 or Google Cloud Storage. An idempotent Snowflake loader reads from the cloud stage and loads into the RAW layer with full row-count reconciliation and a per-batch idempotency ledger.

**Source dataset:** [List of MSME Registered Units under UDYAM](https://www.data.gov.in/)
**Publisher:** Ministry of Micro, Small and Medium Enterprises, Government of India
**Resource ID:** `8b68ae56-84cf-4728-a0a6-1be11028dea7`
**Reported volume:** 43,417,872+ records

> Record counts reflect source data. Unique supplier counts require entity-level deduplication.

---

## Current Production Status

### Implemented

- Timestamp-based run identity with UUID-derived suffix
- Batch-level atomic persistence (temp write → fsync → replace)
- Append-only batch manifest (`manifest.jsonl`)
- Atomic checkpoint persistence
- Manifest + artifact validation on resume
- Fail-closed orphaned artifact handling
- Offset/limit pagination with short-page protection
- State-level reconciliation (API total vs. persisted records)
- Run-level reconciliation (all states completed + SUM check)
- SHA-256 batch artifact integrity: checksum written to manifest on persist, verified on resume
- Durable run summary artifact (`run_summary.json`) written atomically at end of every run
- Structured per-execution log file
- Process exit codes (`0` success / `1` failure)
- Structured failure metadata in checkpoints and run summaries
- Centralized environment-driven runtime configuration with validation
- Graceful SIGINT/SIGTERM shutdown with resumable checkpoints
- Retry classification for curl failures, HTTP 429, and transient HTTP 5xx responses
- Bounded exponential backoff with configurable jitter and rate-limit delay
- Automated pytest regression suite
- Cross-platform `curl` (Linux and Windows)
- GitHub Actions CI (test), CD (auto-deploy to EC2 on merge to main), and manual pipeline trigger with state dropdown
- EC2 Linux deployment (Ubuntu 24.04, t3.micro) with virtualenv and screen-based long runs
- Multi-cloud RAW storage backend: **Amazon S3** and Google Cloud Storage
- Object metadata carries the extractor SHA-256 for remote artifact validation
- Idempotent **Snowflake RAW loader** with per-batch ledger, row-count reconciliation, and fail-closed LOADING guard
- Snowflake connected to S3 via Storage Integration (no long-lived AWS keys in Snowflake)
- Least-privilege IAM policy for the extractor service account (`s3:PutObject`, `s3:GetObject` scoped to prefix)

### Planned

- dbt Bronze / Silver / Gold transformations
- Airflow orchestration and scheduling
- Monitoring and alerting
- Data-quality framework
- Data lineage and governance

---

## Target Architecture

```
Government of India
  data.gov.in API
        │
        ▼
Python Extraction Service   ◄── Airflow (orchestration, retries, scheduling)
        │
        ▼
  Amazon S3 RAW
  (CSV batch artifacts)
        │
        ▼
   Snowflake RAW             ◄── Idempotent loader (scripts/load_to_snowflake.py)
        │
        ▼
    dbt BRONZE
        │
        ▼
    dbt SILVER
        │
        ▼
     dbt GOLD
        │
        ▼
BI / Analytics / ML
```

Observability (logs, metrics, alerts) and CI/CD (GitHub Actions → EC2) span all layers.

---

## Features

- State-level API extraction with `filters[State]` parameter
- Offset/limit pagination — 10,000 records per request
- `curl`-based HTTP (cross-platform — Linux and Windows, no third-party HTTP library)
- Exponential backoff with jitter on failure, up to 5 retries
- Short-page protection — unexpected truncated responses are retried, not accepted
- Parallel state processing via `ThreadPoolExecutor`
- Unique timestamp-based run identity with UUID-derived suffix
- Atomic batch CSV writes (temp file → replace + `fsync`)
- Append-only batch manifest (`manifest.jsonl`)
- Checkpoint-based resume at the batch level
- Fail-closed on orphaned artifacts (CSV present but no manifest entry → hard stop)
- SHA-256 checksum computed on every batch CSV and stored in the manifest; verified on resume
- State-level and run-level reconciliation (API totals vs. persisted records)
- Durable run summary artifact (`run_summary.json`) written atomically at end of every run
- Per-execution log file
- API key stored in `.env`, never in source
- Multi-cloud storage: publish batches to **S3** (`s3://`) or GCS (`gs://`) as they complete
- Idempotent Snowflake loader with per-batch ledger and row-count reconciliation

---

## Project Structure

```
Udyam_MSME/
├── udyam_extractor.py        # Core extraction engine
├── run_udyam.py              # Entry point and runtime config
├── config.py                 # Environment-driven runtime configuration
├── storage.py                # Local / S3 / GCS RAW storage abstraction
├── requirements.txt
├── requirements-dev.txt
├── .env                      # Secrets (not committed)
├── .env.example
├── .gitignore
├── Readme.md
├── .github/
│   └── workflows/
│       ├── ci.yml            # Tests on every PR and push
│       ├── cd.yml            # Auto-deploy to EC2 on merge to main
│       └── run-pipeline.yml  # Manual extraction + Snowflake load (state dropdown)
├── scripts/
│   ├── load_to_snowflake.py  # Idempotent S3 → Snowflake RAW loader
│   └── preflight.ps1         # Production host readiness checks
├── snowflake/
│   ├── part 1.sql            # Role, user, database, schema, tables, file formats
│   ├── part 2.sql            # S3 Storage Integration
│   └── part 3.sql            # External stage + verification
├── tests/
│   └── test_production_hardening.py
│
├── output/                   # Runtime — not committed
│   └── <run_id>/
│       ├── manifest.jsonl
│       ├── run_summary.json
│       └── <state>/
│           └── batches/
│               ├── <run_id>_<state>_0.csv
│               └── ...
│
├── checkpoints/              # Runtime — not committed
│   └── <run_id>/
│       └── <state>.json
│
└── logs/                     # Runtime — not committed
    └── udyam_<YYYYMMDD_HHMMSS>.log
```

---

## Requirements

- **Python 3.10+** (Linux or Windows)
- **`curl`** — pre-installed on Ubuntu; included in Windows 10/11
- Dependencies listed in `requirements.txt`
- Development/test dependencies listed in `requirements-dev.txt`

```bash
pip install -r requirements.txt
```

For development and CI:

```bash
pip install -r requirements-dev.txt
```

---

## Setup

**1. Clone the repository and navigate to the project root.**

**2. Create a `.env` file from the template:**

```bash
cp .env.example .env
```

Then fill in your values. Never commit `.env` to Git.

**3. Verify `curl` is available:**

```bash
curl --version
```

---

## Configuration

Runtime configuration is centralized in `config.py` and supplied through environment variables or `.env`.

| Variable | Default | Purpose |
|---|---:|---|
| `UDYAM_TEST_STATE` | `ANDAMAN AND NICOBAR ISLANDS` | Test state; set to `ALL` or empty for all states |
| `UDYAM_MAX_WORKERS` | `3` | Parallel state workers |
| `UDYAM_BATCH_SIZE` | `10000` | Records per API request |
| `UDYAM_MAX_RETRIES` | `5` | Retry attempts per batch |
| `UDYAM_CONNECT_TIMEOUT` | `30` | curl connect timeout (seconds) |
| `UDYAM_MAX_REQUEST_TIME` | `300` | curl max request duration (seconds) |
| `UDYAM_RETRY_BACKOFF_BASE` | `5` | Initial retry backoff (seconds) |
| `UDYAM_RETRY_BACKOFF_MAX` | `60` | Maximum exponential backoff (seconds) |
| `UDYAM_RETRY_JITTER` | `3` | Random retry jitter (seconds) |
| `UDYAM_RATE_LIMIT_DELAY` | `30` | Minimum delay after HTTP 429 (seconds) |
| `UDYAM_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `UDYAM_STORAGE_BACKEND` | `local` | `local`, `s3`, or `gcs` |
| `UDYAM_S3_BUCKET` | — | Required for S3 mode; target RAW bucket |
| `UDYAM_S3_PREFIX` | `udyam/raw` | S3 RAW object prefix |
| `UDYAM_S3_REGION` | — | AWS region (e.g. `ap-south-2`) |
| `UDYAM_S3_ENDPOINT_URL` | — | Optional; for S3-compatible endpoints |
| `UDYAM_GCS_BUCKET` | — | Required for GCS mode; target RAW bucket |
| `UDYAM_GCS_PREFIX` | `udyam/raw` | GCS RAW object prefix |
| `UDYAM_GCS_PROJECT` | — | Optional GCP project used by the GCS client |

`UDYAM_API_KEY` is a required secret and must not be committed.

---

## S3 RAW Storage

The extractor publishes each completed batch directly to Amazon S3. Credentials resolve via the standard AWS chain (environment variables, shared config, or IAM role/task role).

```env
UDYAM_STORAGE_BACKEND=s3
UDYAM_S3_BUCKET=supplier-udyam-raw
UDYAM_S3_PREFIX=udyam/raw
UDYAM_S3_REGION=ap-south-2
```

The S3 layout mirrors the GCS layout:

```text
s3://<bucket>/udyam/raw/
└── run_id=<run_id>/
    ├── manifest.jsonl
    ├── run_summary.json
    └── state=<state>/batches/<batch_id>.csv
```

Each batch upload stores the SHA-256 in object metadata. Post-upload verification reads it back via `HeadObject` (covered by `s3:GetObject`). A resumed run verifies the remote object's presence, size, and checksum before skipping a completed batch.

### IAM policy for the extractor service account

Scope permissions to the `udyam/raw/` prefix only:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::supplier-udyam-raw/udyam/raw/*"
    }
  ]
}
```

### Connecting Snowflake to S3

Snowflake reads from S3 via a Storage Integration — no AWS keys are stored in Snowflake. See `snowflake/part 2.sql` and `snowflake/part 3.sql` for the integration and stage DDL.

---

## GCS RAW Storage

```env
UDYAM_STORAGE_BACKEND=gcs
UDYAM_GCS_BUCKET=your-gcs-bucket
UDYAM_GCS_PREFIX=udyam/raw
```

Uses Application Default Credentials. Do not place service-account keys in the repository.

---

## Snowflake RAW Loader

`scripts/load_to_snowflake.py` is an idempotent loader that reads the run manifest from the Snowflake external stage and loads each SUCCESS batch into the RAW table.

```powershell
$env:UDYAM_RUN_ID = "20260917T174515Z_4366d444"
python scripts/load_to_snowflake.py
```

| Variable | Purpose |
|---|---|
| `SNOWFLAKE_ACCOUNT` | Account identifier (e.g. `ORGNAME-ACCOUNTNAME`) |
| `SNOWFLAKE_USER` | Service user (e.g. `UDYAM_SVC`) |
| `SNOWFLAKE_AUTHENTICATOR` | `snowflake` (password) or `externalbrowser` (SSO) |
| `SNOWFLAKE_PASSWORD` | Required when authenticator is `snowflake` |
| `SNOWFLAKE_ROLE` | Role with loader privileges (e.g. `UDYAM_LOADER`) |
| `SNOWFLAKE_WAREHOUSE` | Compute warehouse |
| `SNOWFLAKE_DATABASE` | Target database |
| `SNOWFLAKE_SCHEMA` | Target schema |
| `SNOWFLAKE_STAGE` | External stage name (e.g. `S3_STAGE`) |
| `SNOWFLAKE_RAW_TABLE` | RAW landing table (default `MSME`) |
| `SNOWFLAKE_INGESTION_BATCH_TABLE` | Idempotency ledger (default `INGESTION_BATCH`) |
| `UDYAM_RUN_ID` | Run to load — must be set explicitly |

**Load flow:**
1. Read `manifest.jsonl` for the configured `UDYAM_RUN_ID` from the external stage
2. For each `SUCCESS` batch: check the `INGESTION_BATCH` ledger
3. Skip if already `LOADED` with matching row count and checksum
4. Fail closed if status is `LOADING` (ambiguous — investigate before retrying)
5. `COPY INTO` the RAW table, verify row count, update ledger; commit both atomically

See `snowflake/part 1.sql` for the full DDL (role, user, tables, file formats).

---

## Running the Pipeline

### Single state (for testing)

```powershell
$env:UDYAM_TEST_STATE = "GOA"
python .\run_udyam.py
```

### Full extraction (all states)

Remove or blank `UDYAM_TEST_STATE` in `.env`, then:

```powershell
python .\run_udyam.py
```

### Resume a specific run

```powershell
$env:UDYAM_RUN_ID = "20260917T174515Z_4366d444"
python .\run_udyam.py
```

When `UDYAM_RUN_ID` is not set, a new run ID is generated automatically.

**Exit codes:** `0` = all states completed + reconciliation passed | `1` = failure

### Load to Snowflake

```powershell
$env:UDYAM_RUN_ID = "20260917T174515Z_4366d444"
python scripts/load_to_snowflake.py
```

---

## How It Works

### Run Identity

Every execution gets a unique timestamp-based run ID:

```
20260912T165020Z_0ab2cda0
  └─ UTC timestamp   └─ 8-char UUID-derived suffix (uuid4().hex[:8])
```

All output, checkpoint, and S3 paths are scoped to this run ID.

### Pagination

```
offset=0,     limit=10000  → Batch 1
offset=10000, limit=10000  → Batch 2
offset=20000, limit=10000  → Batch 3
...
```

### Persistence Order

```
API response
    ↓
Atomic batch CSV   (temp write → fsync → replace)
    ↓
SHA-256 checksum
    ↓
S3 upload          (PutObject + HeadObject verification)
    ↓
Manifest entry     (SUCCESS appended to manifest.jsonl)
    ↓
Atomic checkpoint  (state progress updated)
```

Recovery trusts a batch only when **both** a manifest entry and a validated remote object exist.

### Short-Page Protection

A page with fewer than 10,000 records is accepted only when it is the final page:

```
offset + record_count >= API total
```

### Parallel Processing

Up to `MAX_WORKERS` states are extracted concurrently. Start at `3` — the Udyam API can throttle under high concurrency.

### Reconciliation

State-level (per state, after all batches complete):
```
API total records == records written
```

Run-level (after all states complete):
```
All states = COMPLETED  AND  SUM(API totals) == SUM(records written)
```

### Checkpoints

```json
{
    "run_id": "20260917T174515Z_4366d444",
    "state": "GOA",
    "total_records": 86010,
    "records_written": 86010,
    "last_completed_offset": 86010,
    "status": "COMPLETED",
    "updated_at": "2026-09-17T17:48:00+00:00"
}
```

Status values: `NOT_STARTED` | `IN_PROGRESS` | `COMPLETED` | `FAILED`

### Failure Metadata

```json
{
    "status": "FAILED",
    "failure_reason": "RETRY_EXHAUSTED",
    "failure_stage": "API_FETCH",
    "failure_detail": "Failed to fetch state=...",
    "retry_count": 5,
    "http_status": 503,
    "failed_at": "2026-09-17T..."
}
```

### Graceful Shutdown

`Ctrl+C` (`SIGINT`) or `SIGTERM` requests a cooperative shutdown. The current API request finishes, workers stop before starting another batch, and the process exits with code `1`. Checkpoints remain resumable.

### API Retry Policy

Retries transient curl failures, HTTP `429`, `500`, `502`, `503`, `504` using bounded exponential backoff and jitter. Non-retryable HTTP 4xx responses fail the state immediately.

### Resume Behavior

```
State A  → COMPLETED      → SKIP
State B  → IN_PROGRESS    → RESUME from last_completed_offset
State C  → FAILED         → Restart; recovered batches are validated, remaining fetched
```

---

## Output

### CSV Schema

| Column | Description |
|---|---|
| `LG_ST_Code` | State code |
| `State` | State name |
| `LG_DT_Code` | District code |
| `District` | District name |
| `Pincode` | PIN code |
| `RegistrationDate` | Udyam registration date |
| `EnterpriseName` | Registered enterprise name |
| `CommunicationAddress` | Enterprise address |
| `Activities` | JSON array of NIC codes and descriptions |

### Manifest

`manifest.jsonl` — one line per successfully persisted batch:

```json
{
    "batch_id": "20260917T174515Z_4366d444_GOA_0",
    "run_id": "20260917T174515Z_4366d444",
    "state": "GOA",
    "offset": 0,
    "record_count": 10000,
    "batch_file": "s3://supplier-udyam-raw/udyam/raw/run_id=.../state=GOA/batches/....csv",
    "checksum": "a3f1c2d4e5b6...",
    "status": "SUCCESS",
    "persisted_at": "2026-09-17T17:45:15+00:00"
}
```

### Run Summary

`run_summary.json` — written atomically at the end of every run:

```json
{
    "run_id": "20260917T174515Z_4366d444",
    "started_at": "2026-09-17T17:45:15+00:00",
    "completed_at": "2026-09-17T17:48:00+00:00",
    "requested_states": 2,
    "completed_states": 2,
    "failed_states": 0,
    "expected_records": 104114,
    "actual_records": 104114,
    "reconciliation_status": "PASSED",
    "run_status": "COMPLETED"
}
```

---

## CI / CD

### Continuous Integration (`ci.yml`)

Runs on every PR and push to `main` and `aws-migration-prod`:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

### Continuous Deployment (`cd.yml`)

Triggers automatically on every merge to `main`. SSHes into the EC2, pulls latest code, reinstalls dependencies, and runs the test suite to confirm the deploy is healthy.

### Manual Pipeline (`run-pipeline.yml`)

Triggered from **Actions → Run Extraction + Load → Run workflow**. Provides:
- **State dropdown** — all 36 Indian states or `ALL` for a full run
- **Run ID input** — leave blank to start a new run, or provide an ID to resume

The extract job runs first; the load job runs after it completes successfully.

> For a full 43M-record run, use `screen` directly on the EC2 rather than the workflow — GitHub Actions jobs time out at 6 hours.

### GitHub Actions secrets required

| Secret | Purpose |
|---|---|
| `EC2_HOST` | EC2 public IP |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | Private key (`.pem` contents) |
| `UDYAM_API_KEY` | Udyam API key |
| `AWS_ACCESS_KEY_ID` | S3 write credentials |
| `AWS_SECRET_ACCESS_KEY` | S3 write credentials |
| `SNOWFLAKE_PASSWORD` | Snowflake service user password |

## Production Host Preflight

```bash
bash scripts/preflight.ps1
```

Verifies Python 3.10+, `curl`, required runtime directories, Python compilation, and `UDYAM_API_KEY`.

## Security

- Store all secrets only in `.env` — excluded from Git via `.gitignore`
- AWS credentials resolve via the standard chain; do not hard-code keys
- Snowflake uses a Storage Integration for S3 access — no AWS keys stored in Snowflake
- IAM policy is scoped to the `udyam/raw/` prefix with minimum required actions only
- If a key is accidentally committed: revoke immediately, purge from history, issue a new key

---

## Version History

### 3.1.0 — EC2 deployment and CI/CD pipeline

- **Cross-platform `curl`** — removed `.exe` suffix; extractor now runs on Linux and Windows without code changes
- **EC2 Linux deployment** — Ubuntu 24.04, t3.micro (unlimited CPU burst), virtualenv, `screen` for long-running full-state extractions
- **GitHub Actions CD** (`cd.yml`) — auto-deploys to EC2 on merge to `main`; pulls code, reinstalls deps, runs test suite
- **Manual pipeline workflow** (`run-pipeline.yml`) — `workflow_dispatch` with state dropdown (all 36 states + `ALL`) and optional run ID for resuming; extract and load jobs run sequentially
- **Test isolation fix** — `test_configuration_defaults` patches `load_dotenv` to prevent `.env` contents (e.g. blank `UDYAM_TEST_STATE` on the EC2) from leaking into the test suite

### 3.0.0 — AWS migration and Snowflake RAW ingestion

- **Amazon S3 storage backend** — `UDYAM_STORAGE_BACKEND=s3` publishes batches directly to S3 using `boto3`; SHA-256 stored in object metadata and verified post-upload
- **Multi-cloud storage abstraction** — shared `ObjectStorage` base class; `GCSStorage` and `S3Storage` subclasses implement only `_upload` / `_head`; all layout, verification, and manifest sync logic is shared
- **Idempotent Snowflake RAW loader** (`scripts/load_to_snowflake.py`) — reads manifest from Snowflake external stage, loads each SUCCESS batch via `COPY INTO`, reconciles row counts, and maintains a per-batch `INGESTION_BATCH` ledger; supports both password and SSO authentication
- **Snowflake S3 Storage Integration** — Snowflake reads from S3 via IAM role trust, no long-lived AWS keys in Snowflake; DDL in `snowflake/` directory
- **Least-privilege IAM** — extractor service account limited to `s3:PutObject` + `s3:GetObject` scoped to `udyam/raw/*`
- First end-to-end vertical slice: extraction → S3 → Snowflake RAW (104,114 rows verified)

### 2.0.0 — Production hardening

- Structured failure metadata for API, persistence, reconciliation, artifact, shutdown, and unexpected state failures
- Centralized environment-driven configuration with validation
- Graceful SIGINT/SIGTERM shutdown with resumable state checkpoints
- HTTP status classification for retryable 429/5xx and non-retryable 4xx responses
- Configurable bounded exponential backoff, jitter, and rate-limit delay
- Automated pytest regression suite
- Windows GitHub Actions CI
- GCS RAW storage backend with object metadata SHA-256 verification

### 1.7.0 — SHA-256 batch artifact integrity

- SHA-256 checksum computed on every batch CSV immediately after atomic write
- Checksum stored in each `manifest.jsonl` entry and verified on resume

### 1.6.0 — Durable run summary

- Durable `run_summary.json` artifact written atomically at end of every run

### 1.5.0 — Production reliability and reconciliation

- Timestamp-based run identity, atomic persistence, manifest, checkpoints, reconciliation, and exit codes

---

## Data Source Reference

**Platform:** Government of India Open Government Data Platform — https://www.data.gov.in/
**Dataset:** List of MSME Registered Units under UDYAM
**Resource ID:** `8b68ae56-84cf-4728-a0a6-1be11028dea7`
**Reported volume:** 43,417,872+ records

---

## Known Limitations

- No stable record-level unique identifier in the source API
- RAW persistence is CSV; Parquet can be introduced without changing the extraction contract
- Record-level duplicate detection belongs in a downstream Silver-layer transform
- `MAX_WORKERS` is bounded by Udyam API stability — increase gradually

---

## Disclaimer

Record counts and dataset content are based on Udyam metadata available at the time of extraction. The source is updated periodically. The reported record count does not represent unique companies or suppliers without additional entity-level deduplication.
