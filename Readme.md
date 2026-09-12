# Udyam MSME Extractor

Version

**1.5.0**

Python-based data extraction pipeline for retrieving MSME registered-unit data from the Government of India's Udyam dataset through the `data.gov.in` API.

The pipeline extracts data at the **State → District** level, handles API pagination, retries failed requests, maintains execution checkpoints, supports parallel district processing, and stores monthly snapshots.

---

## Features

- State-level API extraction

- Pagination with configurable batch size

- 10,000 records per API request

- `curl.exe` based API requests

- Automatic retry handling

- Exponential backoff with jitter

- Connection and request timeouts

- Unique run-level execution isolation

- Checkpoint-based resume capability with batch recovery

- Completed state detection within the current run

- Parallel state processing

- Run-level execution timing

- Run-level execution timing

- Overall execution timing

- Deterministic batch CSV output per State

- Separate execution logs

- API key stored outside source code

- Failed states do not stop the complete extraction run

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

**## Project Structure**

Current production-oriented structure:

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
│   └── <run_id>/
│       ├── manifest.jsonl
│       └── <state>/
│           └── batches/
│               ├── <run_id>_<state>_0.csv
│               ├── <run_id>_<state>_10000.csv
│               └── ...
│
├── checkpoints/
│   └── <run_id>/
│       └── <state>.json
│
└── logs/
    └── udyam_master_YYYYMMDD_HHMMSS.log

output/, checkpoints/, and logs/ are runtime artifacts and should not be committed to Git.

**---**

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

 ├── ARARIA       ── Worker 1

 ├── ARWAL        ── Worker 2

 └── AURANGABAD   ── Worker 3

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

limit  = 10000

Request 2

offset = 10000

limit  = 10000

Request 3

offset = 20000

limit  = 10000

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

**## Run Identity**

Every execution receives a unique run ID.

Example:

20260912T165020Z_0ab2cda0

The run ID contains a UTC timestamp and short UUID suffix.

A specific run can be resumed with:

$env:UDYAM_RUN_ID = "20260912T165020Z_0ab2cda0"

When no run ID is supplied, a new run ID is generated automatically.

Batch Identity and Persistence

Each API batch has a deterministic ID:

<run_id>_<state>_<offset>

Each successful batch is written as an individual CSV artifact under:

output/<run_id>/<state>/batches/

Batch files are written atomically through a temporary file followed by replacement.

Every successful batch is also recorded in:

output/<run_id>/manifest.jsonl

The persistence order is:

API response
    |
    v
Atomic batch CSV
    |
    v
Manifest SUCCESS entry
    |
    v
Atomic checkpoint update

Recovery trusts a batch only when both its successful manifest entry and physical non-empty artifact exist.

If an orphaned batch artifact exists without a manifest entry, the extractor fails closed rather than overwriting it.

**---**

**## Output**

The extractor produces one CSV artifact per API batch.

Naming convention:

<run_id>_<state>_<offset>.csv

Example:

20260912T165020Z_0ab2cda0_ANDAMAN AND NICOBAR ISLANDS_0.csv

This batch-oriented layout provides independently recoverable artifacts suitable for later raw-storage and warehouse loading.

**---**

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

**## Execution Flow

run_udyam.py
      |
      v
Load environment configuration
      |
      v
Determine RUN_ID
      |
      v
Validate requested States
      |
      v
Extract States
      |
      v
For each State
      |
      v
Checkpoint / batch recovery
      |
      v
API request + pagination
      |
      v
Short-page validation and retry
      |
      v
Atomic batch persistence
      |
      v
Manifest entry
      |
      v
Atomic checkpoint update
      |
      v
State-level reconciliation
      |
      v
Run-level reconciliation
      |
      v
RUN COMPLETED / RUN FAILED

Pagination Safety

A full page of 10,000 records is accepted.

A short page is accepted only when it is the final page:

offset + record_count >= API total

An unexpected short page is retried at the same offset.

This prevents transient short API responses from prematurely ending extraction.

Reconciliation

State-level

API total records == persisted records

A mismatch causes the state to fail.

Run-level

A run succeeds only when:

All requested states are COMPLETED
AND
Every state has an API total
AND
SUM(API totals) == SUM(records written)

The runner returns:

0 = successful run
1 = failed run or reconciliation failure

--------------------+

      |                    |

      v                    v

 District A            District B

      |                    |

      v                    v

Checkpoint             Checkpoint

      |                    |

      v                    v

API Request             API Request

      |                    |

      v                    v

Pagination              Pagination

      |                    |

      v                    v

CSV Output              CSV Output

      |                    |

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

Completed states and persisted batches are skipped or recovered.

Incomplete states resume using checkpoints and batch artifacts.

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

├── .env                    # NOT committed

│

├── udyam_extractor.py

├── run_udyam.py

├── udyam_state_district.json

│

├── output/                 # NOT committed

├── checkpoints/            # NOT committed

└── logs/                   # NOT committed

```

---

**## Version History

1.5.0

Production reliability and reconciliation release.

Key improvements:

Unique run identity

Deterministic batch identity

Atomic batch persistence

Append-only batch manifest

Atomic checkpoint persistence

Batch artifact validation

Batch recovery

Fail-closed orphan artifact handling

Short-page pagination safety

State-level reconciliation

Run-level reconciliation

Exit code based on run success

Data Source Reference**

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