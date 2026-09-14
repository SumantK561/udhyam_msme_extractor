# Udyam MSME Extractor

**Version 1.6.0**

Production-grade Python pipeline for extracting MSME registered-unit data from the Government of India's Udyam dataset via the `data.gov.in` API. Designed for Supplier.io's supplier intelligence ingestion workflow.

---

## What It Does

Retrieves all 43M+ MSME records from the Udyam portal, processing one Indian state at a time, with parallel state workers. Each API page (10,000 records) is atomically persisted as an individual CSV artifact. Interrupted runs resume from the last successfully persisted batch. Previously persisted and validated batches are not re-fetched; failed or incomplete API requests may be retried.

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
- Durable run summary artifact (`run_summary.json`) written atomically at end of every run
- Structured per-execution log file
- Process exit codes (`0` success / `1` failure)

### Planned
- Object-storage landing layer (raw CSV → cloud bucket)
- Snowflake ingestion (RAW layer)
- dbt Bronze / Silver / Gold transformations
- Airflow orchestration and scheduling
- CI/CD deployment pipeline
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
Raw / Landing Storage
(CSV batch artifacts)
        │
        ▼
   Snowflake RAW
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

Observability (logs, metrics, alerts) and CI/CD (GitHub Actions → Windows Server) span all layers. The extractor currently implements the extraction and local persistence layer only.

---

## Features

- State-level API extraction with `filters[State]` parameter
- Offset/limit pagination — 10,000 records per request
- `curl.exe`-based HTTP (Windows-native, no third-party HTTP library)
- Exponential backoff with jitter on failure, up to 5 retries
- Short-page protection — unexpected truncated responses are retried, not accepted
- Parallel state processing via `ThreadPoolExecutor`
- Unique timestamp-based run identity with UUID-derived suffix
- Atomic batch CSV writes (temp file → replace + `fsync`)
- Append-only batch manifest (`manifest.jsonl`)
- Checkpoint-based resume at the batch level
- Fail-closed on orphaned artifacts (CSV present but no manifest entry → hard stop)
- State-level and run-level reconciliation (API totals vs. persisted records)
- Durable run summary artifact (`run_summary.json`) written atomically at end of every run
- Per-execution log file
- API key stored in `.env`, never in source

---

## Project Structure

```
Udyam_MSME/
├── udyam_extractor.py        # Core extraction engine
├── run_udyam.py              # Entry point and runtime config
├── .env                      # API key (not committed)
├── .gitignore
├── Readme.md
│
├── output/                   # Runtime — not committed
│   └── <run_id>/
│       ├── manifest.jsonl
│       ├── run_summary.json
│       └── <state>/
│           └── batches/
│               ├── <run_id>_<state>_0.csv
│               ├── <run_id>_<state>_10000.csv
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

- **Python 3.10+** (Windows)
- **`curl.exe`** — included in Windows 10/11; verify with `curl.exe --version`
- **`python-dotenv`** — the only third-party Python dependency

```powershell
pip install python-dotenv
```

---

## Setup

**1. Clone the repository and navigate to the project root.**

**2. Create a `.env` file:**

```env
UDYAM_API_KEY=YOUR_API_KEY
```

Never commit `.env` to Git.

**3. Verify `curl.exe` is available:**

```powershell
curl.exe --version
```

---

## Configuration

All runtime configuration lives in `run_udyam.py`.

| Variable | Current Value | Purpose |
|---|---|---|
| `TEST_STATE` | `"ANDAMAN AND NICOBAR ISLANDS"` | Development/test state; set to `None` for all states |
| `MAX_WORKERS` | `3` | Parallel state worker threads |

> **Current repository configuration:** `TEST_STATE` is intentionally set to `"ANDAMAN AND NICOBAR ISLANDS"` for controlled testing. Do not change it to `None` until single-state validation is complete.

Core constants in `udyam_extractor.py` (not normally changed):

| Constant | Value | Purpose |
|---|---|---|
| `BATCH_SIZE` | `10000` | Records per API request |
| `MAX_RETRIES` | `5` | Retry attempts per batch |
| `CONNECT_TIMEOUT` | `30` | curl connect timeout (seconds) |
| `MAX_REQUEST_TIME` | `300` | curl max request duration (seconds) |

---

## Running the Pipeline

### Single state (for testing)

```python
# in run_udyam.py
TEST_STATE = "BIHAR"
```

```powershell
python .\run_udyam.py
```

### Full extraction (all states)

```python
# in run_udyam.py
TEST_STATE = None
```

```powershell
python .\run_udyam.py
```

### Resume a specific run

```powershell
$env:UDYAM_RUN_ID = "20260912T165020Z_0ab2cda0"
python .\run_udyam.py
```

When `UDYAM_RUN_ID` is not set, a new run ID is generated automatically.

**Exit codes:** `0` = all states completed + reconciliation passed | `1` = failure

---

## How It Works

### Run Identity

Every execution gets a unique timestamp-based run ID:

```
20260912T165020Z_0ab2cda0
  └─ UTC timestamp   └─ 8-char UUID-derived suffix (uuid4().hex[:8])
```

All output and checkpoint paths are scoped to this run ID.

### Pagination

The API is queried with increasing offsets until the full state record count is retrieved:

```
offset=0,     limit=10000  → Batch 1
offset=10000, limit=10000  → Batch 2
offset=20000, limit=10000  → Batch 3
...
```

### Persistence Order

For each batch, persistence happens in strict order:

```
API response
    ↓
Atomic batch CSV   (temp write → fsync → replace)
    ↓
Manifest entry     (SUCCESS appended to manifest.jsonl)
    ↓
Atomic checkpoint  (state progress updated)
```

Recovery trusts a batch only when **both** a manifest entry and a non-empty physical file exist. An orphaned artifact (file without manifest entry) causes a hard stop rather than an overwrite.

### Short-Page Protection

A page with fewer than 10,000 records is accepted only when it is the final page:

```
offset + record_count >= API total
```

If the API returns a short page mid-extraction, the same offset is retried. This prevents transient API truncation from silently ending a run early.

### Parallel Processing

Up to `MAX_WORKERS` states are extracted concurrently:

```
Run
 ├── ANDAMAN AND NICOBAR ISLANDS  ── Worker 1
 ├── ANDHRA PRADESH               ── Worker 2
 └── ARUNACHAL PRADESH            ── Worker 3
        (next state picks up when a worker finishes)
```

Start conservatively at `MAX_WORKERS = 3`. The Udyam API can throttle under high concurrency.

### Reconciliation

State-level (per state, after all batches complete):
```
API total records == records written
```

Run-level (after all states complete):
```
All states = COMPLETED
AND  SUM(API totals) == SUM(records written)
```

A mismatch at either level causes a failure.

### Checkpoints

One checkpoint file per state per run at `checkpoints/<run_id>/<state>.json`:

```json
{
    "run_id": "20260912T165020Z_0ab2cda0",
    "state": "ANDAMAN AND NICOBAR ISLANDS",
    "total_records": 18058,
    "records_written": 18058,
    "last_completed_offset": 18058,
    "status": "COMPLETED",
    "updated_at": "2026-09-12T16:51:22+00:00"
}
```

Status values: `NOT_STARTED` | `IN_PROGRESS` | `COMPLETED` | `FAILED`

### Resume Behavior

If a run is interrupted, re-run with the same `UDYAM_RUN_ID`:

```
State A  → status=COMPLETED           → SKIP
State B  → status=IN_PROGRESS         → RESUME from last_completed_offset
           last_completed_offset=30000
State C  → status=FAILED              → Restart state; previously persisted
                                         batches are recovered, remaining
                                         batches are fetched
```

Previously persisted batches (validated via manifest + artifact check) are not re-fetched.

---

## Output

### CSV Schema

Each batch file contains these columns:

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

`Activities` example:
```json
[{"NIC5DigitId": "79110", "Description": "Travel agency activities"}]
```

### Batch File Naming

```
<run_id>_<state>_<offset>.csv
```

Example:
```
20260912T165020Z_0ab2cda0_ANDAMAN AND NICOBAR ISLANDS_0.csv
20260912T165020Z_0ab2cda0_ANDAMAN AND NICOBAR ISLANDS_10000.csv
```

### Manifest

`output/<run_id>/manifest.jsonl` — one line per successfully persisted batch:

```json
{
    "batch_id": "20260912T165020Z_0ab2cda0_ANDAMAN AND NICOBAR ISLANDS_0",
    "run_id": "20260912T165020Z_0ab2cda0",
    "state": "ANDAMAN AND NICOBAR ISLANDS",
    "offset": 0,
    "record_count": 10000,
    "batch_file": "output\\...\\ANDAMAN AND NICOBAR ISLANDS\\batches\\...csv",
    "status": "SUCCESS",
    "persisted_at": "2026-09-12T16:50:54.146875+00:00"
}
```

### Run Summary

`output/<run_id>/run_summary.json` — written atomically at the end of every run (success or failure):

```json
{
    "run_id": "20260912T165020Z_0ab2cda0",
    "started_at": "2026-09-12T16:50:20+00:00",
    "completed_at": "2026-09-12T16:51:25+00:00",
    "requested_states": 32,
    "completed_states": 32,
    "failed_states": 0,
    "expected_records": 43417872,
    "actual_records": 43417872,
    "reconciliation_status": "PASSED",
    "run_status": "COMPLETED"
}
```

`reconciliation_status` is `"PASSED"` or `"FAILED"`. `run_status` is `"COMPLETED"` or `"FAILED"`. The file uses the same atomic temp-write → `fsync` → replace pattern as batch CSVs and checkpoints.

---

## Logging

A new log file is created per execution at `logs/udyam_<YYYYMMDD_HHMMSS>.log`.

Log entries cover: run ID, state, API request details, offset, retry attempts, records retrieved/written, batch/state/overall elapsed times, and final summary.

Timing is emitted at three levels:

```
BATCH COMPLETE   | Batch=2 | BatchRecords=10000 | Progress=10000/18058 | BatchElapsed=00:01:12
STATE COMPLETED  | State=ANDAMAN AND NICOBAR ISLANDS | Records=18058 | Elapsed=00:02:31
Total elapsed time=00:02:35
```

---

## Pre-Production Checklist

Before running the full 43M-record extraction:

1. Run a single state: `TEST_STATE = "BIHAR"`
2. Validate generated CSVs — row counts, column completeness, `Activities` JSON
3. Confirm record counts match the API `total` field
4. Review log for timeout frequency
5. Check checkpoint and resume behavior (kill mid-run, re-run with same `UDYAM_RUN_ID`)
6. Confirm output directory structure
7. Then set `TEST_STATE = None` and run all states

Recommended initial config:

```python
TEST_STATE  = "BIHAR"
MAX_WORKERS = 3
```

After validation:

```python
TEST_STATE  = None
MAX_WORKERS = 3   # increase gradually if API is stable
```

---

## Troubleshooting

### API timeout (`curl` return code 28)

```
CURL FAILURE | ReturnCode=28
```

Automatic retry will handle transient timeouts. If timeouts are frequent, reduce `MAX_WORKERS`:

```python
MAX_WORKERS = 2
```

### Missing API key

```
UDYAM_API_KEY is not configured.
```

Ensure `.env` exists in the project root and contains:

```env
UDYAM_API_KEY=YOUR_API_KEY
```

### Orphaned batch artifact

The extractor fails closed if a CSV file exists on disk without a corresponding manifest entry. Investigate before deleting the file — this indicates an interrupted write sequence. Delete the orphaned file only after confirming it is incomplete or zero-byte.

---

## Security

- Store the API key only in `.env`
- `.env` is excluded from Git via `.gitignore`
- If a key is accidentally committed: revoke it immediately, purge from history, issue a new key

---

## .gitignore

```gitignore
.env
__pycache__/
*.py[cod]
output/
checkpoints/
logs/
venv/
.venv/
.vscode/
.idea/
.DS_Store
Thumbs.db
```

---

## Version History

### 1.6.0 — Durable run summary

- Durable `run_summary.json` artifact written atomically at end of every run (success and failure paths)
- Run summary schema: `run_id`, `started_at`, `completed_at`, `requested_states`, `completed_states`, `failed_states`, `expected_records`, `actual_records`, `reconciliation_status`, `run_status`
- `started_at` / `completed_at` captured as UTC wall-clock timestamps (separate from `perf_counter` timing)
- `build_run_summary()` in `run_udyam.py`; `write_run_summary()` + `get_run_summary_path()` in `udyam_extractor.py`

### 1.5.0 — Production reliability and reconciliation

- Timestamp-based run identity with UUID-derived suffix (`YYYYMMDDTHHMMSSZ_<8hexchars>`)
- Deterministic batch identity (`run_id_state_offset`)
- Atomic batch CSV persistence via temp-file replacement
- Append-only batch manifest (`manifest.jsonl`)
- Atomic checkpoint persistence
- Batch artifact validation on resume
- Fail-closed orphaned artifact handling
- Short-page pagination safety
- State-level reconciliation
- Run-level reconciliation
- Exit code reflects run success (`0` / `1`)

---

## Data Source Reference

**Platform:** Government of India Open Government Data Platform — https://www.data.gov.in/
**Dataset:** List of MSME Registered Units under UDYAM
**Resource ID:** `8b68ae56-84cf-4728-a0a6-1be11028dea7`
**Catalog UUID:** `0536e86e-3751-4054-84e5-e257d4c94477`
**Reported volume:** 43,417,872+ records

---

## Known Limitations

- The source API does not provide a stable record-level unique identifier for enterprises.
- Current persistence format is CSV; Parquet / object-storage landing is planned.
- Batch artifact validation verifies file existence and non-zero size only; record-level integrity checks are not performed at extraction time.
- Record-level duplicate detection is not performed by the extractor — deduplication belongs in a downstream Silver-layer transform.
- API totals are used for extraction reconciliation but do not establish enterprise uniqueness.
- Run metadata is represented through logs, checkpoints, the batch manifest, and `run_summary.json`; a dedicated upstream ingestion trigger based on this file is planned.
- The extractor runs directly on Windows and is not yet deployed through CI/CD.
- `MAX_WORKERS` concurrency is bounded by Udyam API stability, not local resources — increasing it without validating API behavior can cause widespread timeouts.

---

## Disclaimer

Record counts and dataset content are based on Udyam metadata available at the time of extraction. The source is updated periodically. The reported record count does not represent unique companies or suppliers without additional entity-level validation and deduplication.
