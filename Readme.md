# Udyam MSME Extractor

Python-based data extraction pipeline for retrieving MSME registered-unit data from the Government of India's Udyam dataset through the `data.gov.in` API.

The pipeline extracts data at the **State → District** level, handles API pagination, retries failed requests, maintains execution checkpoints, supports parallel district processing, and stores monthly snapshots.

---

## Features

- State/District based API extraction
- Pagination with configurable batch size
- 10,000 records per API request
- `curl.exe` based API requests
- Automatic retry handling
- Exponential backoff with jitter
- Connection and request timeouts
- Monthly execution isolation
- Checkpoint-based resume capability
- Completed district detection within the current monthly run
- Parallel district processing
- Per-district execution timing
- Per-state execution timing
- Overall execution timing
- Individual CSV output per State/District
- Separate execution logs
- API key stored outside source code
- Failed districts do not stop the complete extraction

---

## Source

**Dataset:** List of MSME Registered Units under UDYAM

**Publisher:** Ministry of Micro, Small and Medium Enterprises

**Platform:** Government of India Open Government Data Platform

**Resource ID:**

```text
8b68ae56-84cf-4728-a0a6-1be11028dea7
```

**Reported source volume:**

```text
43,417,872+ records
```

> The reported record count represents source records and should not be interpreted as the number of unique suppliers without entity-level deduplication and validation.

---

## Project Structure

```text
Udyam_MSME/
│
├── .env
├── .gitignore
├── README.md
│
├── udyam_extractor.py
├── run_udyam.py
├── udyam_state_district.json
│
├── output/
│   └── YYYY-MM/
│       ├── udyam_msme_BIHAR_ARARIA.csv
│       ├── udyam_msme_BIHAR_ARWAL.csv
│       └── ...
│
├── checkpoints/
│   └── YYYY-MM/
│       ├── BIHAR_ARARIA.json
│       ├── BIHAR_ARWAL.json
│       └── ...
│
└── logs/
    ├── udyam_master_YYYYMMDD_HHMMSS.log
    └── ...
```

---

## Requirements

### Python

Recommended:

```text
Python 3.10+
```

The pipeline uses `curl.exe` for API requests and is intended to run in a Windows environment.

### Python Packages

Install the required dependency:

```powershell
pip install python-dotenv
```

---

## Environment Configuration

Create a `.env` file in the project root:

```env
UDYAM_API_KEY=YOUR_API_KEY
```

The API key is loaded through the environment and is not hardcoded into the Python source.

### Important

Do not commit `.env` to Git.

---

## `.gitignore`

Recommended `.gitignore`:

```gitignore
# Environment
.env

# Python
__pycache__/
*.py[cod]
*.pyo

# Output data
output/

# Execution checkpoints
checkpoints/

# Logs
logs/

# Virtual environment
venv/
.venv/
env/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
```

---

## Configuration

The main runtime configuration is located in `run_udyam.py`.

### State Filter

For testing a specific state:

```python
TEST_STATE = "BIHAR"
```

To process all states:

```python
TEST_STATE = None
```

Examples:

```python
TEST_STATE = "BIHAR"
```

```python
TEST_STATE = "MAHARASHTRA"
```

```python
TEST_STATE = None
```

---

## Parallel Processing

Districts are processed in parallel using `ThreadPoolExecutor`.

Current configuration:

```python
MAX_WORKERS = 3
```

This means up to three districts can be processed concurrently within a state.

Example:

```text
BIHAR
 │
 ├── ARARIA       ── Worker 1
 ├── ARWAL        ── Worker 2
 └── AURANGABAD   ── Worker 3
```

When one worker finishes, it picks up the next district.

### Recommended Worker Configuration

Start with:

```python
MAX_WORKERS = 3
```

The Udyam API can experience intermittent timeouts, so increasing concurrency should be done gradually.

Possible progression:

```text
3 workers
   ↓
5 workers
   ↓
Evaluate API stability
```

Avoid unnecessarily high concurrency because increased parallelism can increase API timeouts or throttling.

---

## API Configuration

The Udyam resource is:

```text
https://api.data.gov.in/resource/8b68ae56-84cf-4728-a0a6-1be11028dea7
```

Requests contain:

```text
api-key
format
offset
limit
filters[State]
filters[District]
```

Example:

```text
?api-key=<API_KEY>
&format=json
&offset=0
&limit=10000
&filters[State]=BIHAR
&filters[District]=ARARIA
```

---

## Pagination

The API is queried using an offset/limit mechanism.

Default configuration:

```python
BATCH_SIZE = 10000
```

Example:

```text
Request 1
offset = 0
limit  = 10000

Request 2
offset = 10000
limit  = 10000

Request 3
offset = 20000
limit  = 10000

...
```

The process continues until all records reported by the API have been retrieved.

---

## Retry Handling

API failures are automatically retried.

Current configuration:

```python
MAX_RETRIES = 5
```

Retry delays use exponential backoff with random jitter.

Conceptually:

```text
Attempt 1
   ↓
wait
   ↓
Attempt 2
   ↓
wait
   ↓
Attempt 3
   ↓
wait
   ↓
...
```

Jitter is added to prevent multiple parallel workers from retrying at exactly the same time.

---

## Timeout Configuration

Current configuration:

```python
CONNECT_TIMEOUT = 30
MAX_REQUEST_TIME = 300
```

Meaning:

- Connection timeout: 30 seconds
- Maximum API request duration: 300 seconds

The pipeline specifically handles `curl` return code:

```text
28
```

which indicates a timeout.

---

## Checkpointing

Each State/District has a checkpoint file.

Example:

```text
checkpoints/
└── 2026-08/
    └── BIHAR_ARARIA.json
```

Example checkpoint:

```json
{
    "run_id": "2026-08",
    "state": "BIHAR",
    "district": "ARARIA",
    "total_records": 47494,
    "records_written": 47494,
    "last_completed_offset": 47494,
    "status": "COMPLETED",
    "updated_at": "2026-08-25T20:30:00"
}
```

---

## Resume Behavior

Checkpointing allows an interrupted extraction to resume from the last successfully written batch.

Example:

```text
Total records: 47,494

Batch 1 → 10,000 ✓
Batch 2 → 10,000 ✓
Batch 3 → 10,000 ✓
Batch 4 → API timeout
```

Checkpoint:

```text
last_completed_offset = 30000
status = FAILED
```

When the extraction is restarted:

```text
Resume
  ↓
offset = 30000
  ↓
retrieve remaining records
```

Previously written records do not need to be retrieved again.

---

## Monthly Execution Model

The pipeline uses:

```python
RUN_ID = datetime.now().strftime("%Y-%m")
```

Therefore each month receives an independent extraction run.

Example:

```text
2026-08
2026-09
2026-10
```

Each month has independent:

- Output files
- Checkpoints
- Completion status

### Same Month

If the August extraction is interrupted and restarted:

```text
RUN_ID = 2026-08
```

Existing checkpoints are reused.

A completed district:

```text
status = COMPLETED
```

is skipped.

An incomplete district:

```text
status = IN_PROGRESS
```

resumes from its checkpoint.

A failed district:

```text
status = FAILED
```

is retried.

### New Month

When September starts:

```text
RUN_ID = 2026-09
```

The August checkpoints are not used.

Therefore:

```text
August COMPLETED
       ↓
September
       ↓
Fresh extraction
```

This ensures every monthly run retrieves a fresh snapshot.

---

## Output

Each State/District produces an individual CSV.

Naming convention:

```text
udyam_msme_<STATE>_<DISTRICT>.csv
```

Example:

```text
udyam_msme_BIHAR_ARARIA.csv
```

Monthly output structure:

```text
output/
└── 2026-08/
    ├── udyam_msme_BIHAR_ARARIA.csv
    ├── udyam_msme_BIHAR_ARWAL.csv
    ├── udyam_msme_BIHAR_AURANGABAD.csv
    └── ...
```

---

## CSV Columns

The output contains:

```text
LG_ST_Code
State
LG_DT_Code
District
Pincode
RegistrationDate
EnterpriseName
CommunicationAddress
Activities
```

---

## Logging

A new log file is created for every execution.

Example:

```text
logs/
└── udyam_master_20260825_203000.log
```

The log includes:

- Execution start
- Run ID
- State
- District
- API request
- Offset
- Batch size
- Retry attempts
- API failures
- Records retrieved
- Records written
- District elapsed time
- State elapsed time
- Overall elapsed time
- Final execution summary

---

## Execution Timing

The pipeline records timing at three levels.

### Batch

Example:

```text
BATCH COMPLETE |
Batch=3 |
BatchRecords=10000 |
Progress=30000/47494 |
BatchElapsed=00:02:41
```

### District

Example:

```text
DISTRICT COMPLETED |
State=BIHAR |
District=ARARIA |
Records=47494 |
Elapsed=00:18:42
```

### State

Example:

```text
STATE COMPLETED |
State=BIHAR |
State elapsed time=01:42:16
```

### Overall

Example:

```text
Total elapsed time=01:45:31
```

---

## Running the Pipeline

### 1. Test a Single State

Set:

```python
TEST_STATE = "BIHAR"
```

Run:

```powershell
python .\run_udyam.py
```

---

### 2. Test Another State

Change:

```python
TEST_STATE = "MAHARASHTRA"
```

Then:

```powershell
python .\run_udyam.py
```

---

### 3. Full Extraction

Set:

```python
TEST_STATE = None
```

Then run:

```powershell
python .\run_udyam.py
```

All states and their configured districts will be processed.

---

## Execution Flow

```text
run_udyam.py
      |
      v
Load udyam_state_district.json
      |
      v
Determine RUN_ID (YYYY-MM)
      |
      v
Filter State
      |
      v
Load State Districts
      |
      v
ThreadPoolExecutor
      |
      +--------------------+
      |                    |
      v                    v
 District A            District B
      |                    |
      v                    v
Checkpoint             Checkpoint
      |                    |
      v                    v
API Request             API Request
      |                    |
      v                    v
Pagination              Pagination
      |                    |
      v                    v
CSV Output              CSV Output
      |                    |
      +---------+----------+
                |
                v
        State Summary
                |
                v
        Overall Summary
```

---

## Master State/District File

The extraction uses:

```text
udyam_state_district.json
```

The file contains the State/District combinations used for extraction.

Example structure:

```json
{
    "states": [
        {
            "state": "BIHAR",
            "districts": [
                {
                    "value": "ARARIA",
                    "text": "ARARIA"
                },
                {
                    "value": "ARWAL",
                    "text": "ARWAL"
                }
            ]
        }
    ]
}
```

The `value` field is used as the API filter.

---

## Production Run Recommendations

Before running the complete dataset:

1. Validate the State/District master.
2. Run one State first.
3. Validate the generated CSVs.
4. Check record counts against the API response.
5. Review timeout frequency.
6. Review State and District elapsed times.
7. Confirm checkpoint/resume behavior.
8. Confirm output structure.
9. Then enable all States.

Recommended initial configuration:

```python
TEST_STATE = "BIHAR"
MAX_WORKERS = 3
BATCH_SIZE = 10000
MAX_RETRIES = 5
```

After validation:

```python
TEST_STATE = None
```

---

## Error Recovery

If the process stops unexpectedly:

```powershell
python .\run_udyam.py
```

can be executed again.

The current monthly `RUN_ID` is reused.

Completed districts are skipped.

Incomplete districts resume using their checkpoints.

Example:

```text
BIHAR_ARARIA
status = COMPLETED
→ SKIP

BIHAR_ARWAL
status = IN_PROGRESS
last_completed_offset = 30000
→ RESUME FROM 30000

BIHAR_BANKA
status = FAILED
→ RETRY
```

---

## Troubleshooting

### API Timeout

If the log contains:

```text
API TIMEOUT
```

the request exceeded the configured timeout.

The pipeline automatically retries the request.

If timeouts become frequent, consider reducing:

```python
MAX_WORKERS = 3
```

to:

```python
MAX_WORKERS = 2
```

---

### curl Return Code 28

```text
CURL FAILURE | ReturnCode=28
```

Return code `28` indicates a timeout.

The request is automatically retried according to the retry configuration.

---

### Missing API Key

If the log contains:

```text
UDYAM_API_KEY is not configured.
```

verify `.env` contains:

```env
UDYAM_API_KEY=YOUR_API_KEY
```

---

### Master File Not Found

If:

```text
Master file not found
```

verify:

```text
udyam_state_district.json
```

exists in the project root.

---

## Security

API credentials must be stored outside the source code.

Use:

```text
.env
```

Example:

```env
UDYAM_API_KEY=YOUR_API_KEY
```

Never commit API credentials to Git.

If an API key is accidentally committed:

1. Revoke or rotate the key.
2. Remove the credential from repository history where appropriate.
3. Create a new credential.
4. Update `.env`.

---

## Dependencies

Install:

```powershell
pip install python-dotenv
```

The extraction uses:

```text
curl.exe
```

Verify it is available:

```powershell
curl.exe --version
```

---

## Git Repository Structure

```text
Udyam_MSME/
│
├── README.md
├── .gitignore
├── .env                    # NOT committed
│
├── udyam_extractor.py
├── run_udyam.py
├── udyam_state_district.json
│
├── output/                 # NOT committed
├── checkpoints/            # NOT committed
└── logs/                   # NOT committed
```

---

## Data Source Reference

Government of India Open Government Data Platform:

https://www.data.gov.in/

Dataset:

```text
List of MSME Registered Units under UDYAM
```

Resource ID:

```text
8b68ae56-84cf-4728-a0a6-1be11028dea7
```

Catalog UUID:

```text
0536e86e-3751-4054-84e5-e257d4c94477
```

Reported source volume:

```text
43,417,872+ records
```

---

## Disclaimer

The information and record counts described in this README are based on the Udyam dataset metadata available from the Government of India's Open Government Data Platform at the time of assessment.

The source may be updated periodically, and record counts and individual records may change over time.

The reported number of records should not be treated as the number of unique companies or suppliers without additional entity-level validation and deduplication.
