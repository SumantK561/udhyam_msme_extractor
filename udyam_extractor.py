# Udyam MSME State-level extractor

import csv
import json
import os
import random
import subprocess
import tempfile
import time
import threading
import hashlib

from dataclasses import dataclass

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from config import load_settings
from storage import StorageError, build_storage


BASE_URL = (
    "https://api.data.gov.in/resource/"
    "8b68ae56-84cf-4728-a0a6-1be11028dea7"
)

SETTINGS = load_settings()

BATCH_SIZE = SETTINGS.batch_size
MAX_RETRIES = SETTINGS.max_retries
CONNECT_TIMEOUT = SETTINGS.connect_timeout
MAX_REQUEST_TIME = SETTINGS.max_request_time
RETRY_BACKOFF_BASE = SETTINGS.retry_backoff_base
RETRY_BACKOFF_MAX = SETTINGS.retry_backoff_max
RETRY_JITTER = SETTINGS.retry_jitter
RATE_LIMIT_DELAY = SETTINGS.rate_limit_delay
STORAGE = build_storage(SETTINGS)

RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}

OUTPUT_ROOT = Path("output")
CHECKPOINT_ROOT = Path("checkpoints")
LOG_ROOT = Path("logs")

CSV_HEADERS = [
    "LG_ST_Code",
    "State",
    "LG_DT_Code",
    "District",
    "Pincode",
    "RegistrationDate",
    "EnterpriseName",
    "CommunicationAddress",
    "Activities",
]


# ---------------------------------------------------------------------------
# Manifest synchronization
# ---------------------------------------------------------------------------

# States are processed concurrently, so multiple worker threads can write
# to the same run-level manifest.jsonl.
MANIFEST_LOCK = threading.Lock()

# A shutdown request is cooperative: the current HTTP call is allowed to finish,
# then workers stop before starting another batch.
SHUTDOWN_EVENT = threading.Event()


class ExtractionError(Exception):
    """Machine-readable extraction failure."""

    def __init__(
        self,
        reason,
        stage,
        detail="",
        retry_count=0,
        http_status=None,
    ):
        super().__init__(detail or reason)
        self.reason = reason
        self.stage = stage
        self.detail = detail
        self.retry_count = retry_count
        self.http_status = http_status


class ShutdownRequested(ExtractionError):
    """Raised when a graceful process shutdown has been requested."""

    def __init__(self):
        super().__init__(
            reason="SHUTDOWN_REQUESTED",
            stage="SHUTDOWN",
            detail="Process shutdown requested",
        )


def request_shutdown():
    """Request cooperative shutdown of extraction workers."""
    SHUTDOWN_EVENT.set()


def reset_shutdown():
    """Reset the shutdown event for tests or a new in-process run."""
    SHUTDOWN_EVENT.clear()


def is_shutdown_requested():
    """Return True when a graceful shutdown has been requested."""
    return SHUTDOWN_EVENT.is_set()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logger(log_level=None):
    import logging

    LOG_ROOT.mkdir(parents=True, exist_ok=True)

    path = LOG_ROOT / (
        f"udyam_{datetime.now():%Y%m%d_%H%M%S}.log"
    )

    logger = logging.getLogger("udyam")
    level_name = (log_level or SETTINGS.log_level).upper()
    logger.setLevel(getattr(logging, level_name))
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    fh = logging.FileHandler(
        path,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.log_file = path

    return logger


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def format_elapsed(seconds):
    s = int(seconds)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)

    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"

    return f"{m:02d}:{s:02d}"


def reconcile_state(
    state,
    total_records,
    records_written,
    logger,
) -> bool:
    """
    Validate that the number of persisted records exactly matches
    the record count reported by the source API.

    Returns True when reconciliation passes, otherwise False.
    """

    if total_records is None:
        logger.error(
            "RECONCILIATION FAILED | "
            "State=%s | "
            "Reason=MissingAPITotal | "
            "RecordsWritten=%s",
            state,
            records_written,
        )
        return False

    expected = int(total_records)
    actual = int(records_written)

    if actual < expected:
        logger.error(
            "RECONCILIATION FAILED | "
            "State=%s | "
            "ExpectedRecords=%s | "
            "ActualRecords=%s | "
            "Difference=%s",
            state,
            expected,
            actual,
            actual - expected,
        )
        return False

    if actual > expected:
        # API total count increased during extraction (new registrations).
        # All available records were fetched — treat as a warning, not failure.
        logger.warning(
            "RECONCILIATION PASSED WITH GROWTH | "
            "State=%s | "
            "ExpectedRecords=%s | "
            "ActualRecords=%s | "
            "NewRegistrationsDuringExtraction=%s",
            state,
            expected,
            actual,
            actual - expected,
        )

    logger.info(
        "RECONCILIATION PASSED | "
        "State=%s | "
        "ExpectedRecords=%s | "
        "ActualRecords=%s",
        state,
        expected,
        actual,
    )

    return True


# ---------------------------------------------------------------------------
# Run identity
# ---------------------------------------------------------------------------

def get_run_id(
    existing_run_id: Optional[str] = None,
) -> str:
    """
    Return an existing run ID for resume/retry scenarios,
    otherwise generate a new unique UTC run ID.

    Format:
        YYYYMMDDTHHMMSSZ_<8-char-uuid>

    Example:
        20260912T061530Z_a81f92c4
    """

    if existing_run_id:
        return existing_run_id.strip()

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    unique_id = uuid4().hex[:8]

    return f"{timestamp}_{unique_id}"


# ---------------------------------------------------------------------------
# Batch identity
# ---------------------------------------------------------------------------

def get_batch_id(
    run_id: str,
    state: str,
    offset: int,
) -> str:
    """
    Generate a deterministic identifier for an extraction batch.

    A batch is uniquely identified by:

        run_id + state + offset
    """

    return f"{run_id}_{state}_{offset}"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest_path(
    run_id: str,
) -> Path:
    """
    Return the append-only manifest path for an extraction run.
    """

    run_dir = OUTPUT_ROOT / run_id

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return run_dir / "manifest.jsonl"

def calculate_file_sha256(path: Path) -> str:
    """
    Calculate the SHA-256 checksum of a file.
    """
    sha256 = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()

def get_run_summary_path(
    run_id: str,
) -> Path:
    """
    Return the durable run summary path for an extraction run.
    """

    run_dir = OUTPUT_ROOT / run_id

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return run_dir / "run_summary.json"


def write_run_summary(
    run_id: str,
    summary: dict,
) -> None:
    """
    Atomically persist the final run-level summary.

    The summary is written to a temporary file, flushed to disk,
    fsynced, and then atomically replaced.
    """

    path = get_run_summary_path(run_id)

    temp_path = path.with_suffix(".tmp")

    payload = json.dumps(
        summary,
        indent=4,
        ensure_ascii=False,
    )

    try:
        with temp_path.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as file:

            file.write(payload)

            file.flush()

            os.fsync(
                file.fileno()
            )

        temp_path.replace(path)
        STORAGE.sync_run_summary(run_id, path)

    except Exception:
        try:
            temp_path.unlink(
                missing_ok=True
            )
        except OSError:
            pass

        raise

def write_batch_manifest(
    run_id: str,
    state: str,
    offset: int,
    record_count: int,
    batch_path: Path,
    checksum: str,
    status: str = "SUCCESS",
) -> None:
    """
    Append metadata for a physically persisted extraction batch.

    The manifest is append-only. Each line represents one batch and records
    the physical batch artifact used for recovery.
    """

    batch_id = get_batch_id(
        run_id,
        state,
        offset,
    )

    manifest_record = {
        "batch_id": batch_id,
        "run_id": run_id,
        "state": state,
        "offset": offset,
        "record_count": record_count,
        "batch_file": str(batch_path),
        "checksum": checksum,
        "status": status,
        "persisted_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    manifest_path = get_manifest_path(
        run_id
    )

    with MANIFEST_LOCK:

        with manifest_path.open(
            "a",
            encoding="utf-8",
            newline="\n",
        ) as file:

            file.write(
                json.dumps(
                    manifest_record,
                    ensure_ascii=False,
                )
                + "\n"
            )

            file.flush()
            os.fsync(file.fileno())

        STORAGE.sync_manifest(run_id, manifest_path)


def get_persisted_batch(
    run_id: str,
    state: str,
    offset: int,
) -> Optional[dict]:
    """
    Return the successful manifest record for a batch.

    Returns None when the batch has not been successfully persisted.
    """

    batch_id = get_batch_id(
        run_id,
        state,
        offset,
    )

    manifest_path = get_manifest_path(
        run_id
    )

    if not manifest_path.exists():
        return None

    with MANIFEST_LOCK:

        with manifest_path.open(
            "r",
            encoding="utf-8",
        ) as file:

            for line in file:

                line = line.strip()

                if not line:
                    continue

                try:
                    record = json.loads(line)

                except json.JSONDecodeError:
                    continue

                if (
                    record.get("batch_id") == batch_id
                    and record.get("status") == "SUCCESS"
                ):
                    return record

    return None


def is_batch_artifact_valid(
    manifest_record,
) -> bool:
    """Validate a persisted batch through the configured storage backend."""
    valid, _ = STORAGE.validate_artifact(
        manifest_record,
        calculate_file_sha256,
    )
    return valid

def is_batch_persisted(
    run_id: str,
    state: str,
    offset: int,
) -> bool:
    """
    Return True when the batch has already been
    successfully persisted.
    """

    return (
        get_persisted_batch(
            run_id,
            state,
            offset,
        )
        is not None
    )


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def checkpoint_path(
    run_id,
    state,
):
    path = CHECKPOINT_ROOT / run_id

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path / f"{state}.json"


def output_path(
    run_id,
    state,
):
    path = OUTPUT_ROOT / run_id

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path / f"udyam_msme_{state}.csv"


def batch_output_path(
    run_id,
    state,
    offset,
):
    """Return the deterministic physical path for one extraction batch."""

    batch_id = get_batch_id(
        run_id,
        state,
        offset,
    )

    batch_dir = (
        OUTPUT_ROOT
        / run_id
        / state
        / "batches"
    )

    batch_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return batch_dir / f"{batch_id}.csv"


def load_checkpoint(
    run_id,
    state,
):
    path = checkpoint_path(
        run_id,
        state,
    )

    if path.exists():

        try:
            return json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            json.JSONDecodeError,
            OSError,
        ):
            pass

    return {
        "run_id": run_id,
        "state": state,
        "total_records": None,
        "records_written": 0,
        "last_completed_offset": 0,
        "status": "NOT_STARTED",
    }


def save_checkpoint(
    run_id,
    state,
    cp,
):
    """
    Atomically persist checkpoint state.

    The checkpoint is written to a temporary file,
    flushed to disk, fsynced, and then atomically replaced.
    """

    cp["updated_at"] = datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )

    path = checkpoint_path(
        run_id,
        state,
    )

    temp_path = path.with_suffix(
        ".tmp"
    )

    payload = json.dumps(
        cp,
        indent=4,
        ensure_ascii=False,
    )

    with temp_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:

        file.write(payload)
        file.flush()
        os.fsync(
            file.fileno()
        )

    temp_path.replace(path)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_batch(
    api_key,
    state,
    offset,
    logger,
):
    from urllib.parse import quote

    url = (
        f"{BASE_URL}"
        f"?api-key={quote(api_key)}"
        f"&format=json"
        f"&offset={offset}"
        f"&limit={BATCH_SIZE}"
        f"&filters%5BState%5D={quote(state)}"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        if is_shutdown_requested():
            raise ShutdownRequested()

        temp_path = None
        started = time.perf_counter()

        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".json",
            ) as file:
                temp_path = file.name

            cmd = [
                "curl",
                "-sS",
                "-L",
                "--connect-timeout",
                str(CONNECT_TIMEOUT),
                "--max-time",
                str(MAX_REQUEST_TIME),
                "-H",
                "accept: application/json",
                "-o",
                temp_path,
                "-w",
                "%{http_code}",
                url,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            elapsed = time.perf_counter() - started

            try:
                http_status = int((result.stdout or "").strip() or "0")
            except ValueError:
                http_status = 0

            if result.returncode:
                detail = result.stderr.strip() or "curl request failed"
                logger.error(
                    "CURL FAILURE | State=%s | Offset=%s | "
                    "ReturnCode=%s | HTTPStatus=%s | Elapsed=%s | Error=%s",
                    state,
                    offset,
                    result.returncode,
                    http_status or "N/A",
                    format_elapsed(elapsed),
                    detail,
                )
                failure_reason = (
                    "TIMEOUT"
                    if result.returncode == 28
                    else "CURL_REQUEST_FAILED"
                )
            elif http_status in RETRYABLE_HTTP_STATUS_CODES:
                logger.warning(
                    "API RETRYABLE HTTP ERROR | State=%s | Offset=%s | "
                    "HTTPStatus=%s | Attempt=%s/%s",
                    state,
                    offset,
                    http_status,
                    attempt,
                    MAX_RETRIES,
                )
                failure_reason = "RATE_LIMITED" if http_status == 429 else "HTTP_5XX"
            elif http_status >= 400:
                detail = result.stderr.strip() or f"HTTP {http_status}"
                raise ExtractionError(
                    reason="HTTP_CLIENT_ERROR",
                    stage="API_FETCH",
                    detail=detail,
                    retry_count=attempt - 1,
                    http_status=http_status,
                )
            else:
                try:
                    data = json.loads(
                        Path(temp_path).read_text(
                            encoding="utf-8"
                        )
                    )

                    if data.get("status") == "ok":
                        records = data.get("records") or []
                        count = len(records)
                        total = int(data.get("total") or 0)

                        logger.info(
                            "API RESPONSE | State=%s | Offset=%s | "
                            "Count=%s | Total=%s | HTTPStatus=%s | Elapsed=%s",
                            state,
                            offset,
                            count,
                            total,
                            http_status,
                            format_elapsed(elapsed),
                        )

                        if (
                            count < BATCH_SIZE
                            and offset + count < total
                        ):
                            logger.warning(
                                "SHORT API PAGE | State=%s | Offset=%s | "
                                "Count=%s | Total=%s | ExpectedAtLeast=%s | "
                                "RetryingSameOffset",
                                state,
                                offset,
                                count,
                                total,
                                BATCH_SIZE,
                            )
                            failure_reason = "SHORT_PAGE"
                        else:
                            return data

                    else:
                        logger.error(
                            "API ERROR | State=%s | Offset=%s | Response=%s",
                            state,
                            offset,
                            json.dumps(data)[:1000],
                        )
                        failure_reason = "API_RESPONSE_ERROR"

                except (
                    json.JSONDecodeError,
                    OSError,
                ) as exc:
                    logger.error(
                        "INVALID API RESPONSE | State=%s | Offset=%s | Error=%s",
                        state,
                        offset,
                        exc,
                    )
                    failure_reason = "INVALID_API_RESPONSE"

        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        if is_shutdown_requested():
            raise ShutdownRequested()

        if attempt < MAX_RETRIES:
            delay = min(
                RETRY_BACKOFF_MAX,
                RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
            ) + random.uniform(0, RETRY_JITTER)

            # A 429 should honor a conservative delay; other transient failures
            # use the same bounded exponential backoff.
            if failure_reason == "RATE_LIMITED":
                delay = max(delay, RATE_LIMIT_DELAY)

            logger.warning(
                "RETRYING | State=%s | Offset=%s | Reason=%s | "
                "Attempt=%s/%s | RetryIn=%.1f seconds",
                state,
                offset,
                failure_reason,
                attempt,
                MAX_RETRIES,
                delay,
            )

            if SHUTDOWN_EVENT.wait(delay):
                raise ShutdownRequested()

    raise ExtractionError(
        reason="RETRY_EXHAUSTED",
        stage="API_FETCH",
        detail=f"Failed to fetch state={state}, offset={offset}",
        retry_count=MAX_RETRIES,
        http_status=http_status if "http_status" in locals() else None,
    )


# ---------------------------------------------------------------------------
# CSV persistence
# ---------------------------------------------------------------------------

def write_batch_file(
    path,
    records,
):
    """
    Write one complete batch to a temporary file and atomically publish it.

    The final batch artifact is never intentionally exposed as a partial CSV.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = path.with_suffix(".tmp")

    try:
        with temp_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=CSV_HEADERS,
                extrasaction="ignore",
            )

            writer.writeheader()

            for record in records:
                writer.writerow(
                    {
                        header: record.get(
                            header,
                            "",
                        )
                        for header in CSV_HEADERS
                    }
                )

            file.flush()
            os.fsync(file.fileno())

        temp_path.replace(path)

    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return len(records)


# ---------------------------------------------------------------------------
# State extraction
# ---------------------------------------------------------------------------

def mark_state_failed(
    cp,
    run_id,
    state,
    logger,
    reason,
    stage,
    detail="",
    retry_count=0,
    http_status=None,
):
    """Persist structured failure metadata and return the failed checkpoint."""
    failed_at = datetime.now(timezone.utc).isoformat()

    cp.update(
        {
            "run_id": run_id,
            "state": state,
            "status": "FAILED",
            "last_completed_offset": int(cp.get("last_completed_offset", 0)),
            "records_written": int(cp.get("records_written", 0)),
            "total_records": cp.get("total_records"),
            "failure_reason": reason,
            "failure_stage": stage,
            "failure_detail": detail[:2000] if detail else "",
            "retry_count": retry_count,
            "http_status": http_status,
            "failed_at": failed_at,
        }
    )
    save_checkpoint(run_id, state, cp)

    logger.error(
        "STATE FAILED | State=%s | Reason=%s | Stage=%s | "
        "RetryCount=%s | HTTPStatus=%s | Detail=%s",
        state,
        reason,
        stage,
        retry_count,
        http_status if http_status is not None else "N/A",
        detail[:500] if detail else "",
    )
    return cp


def extract_state(
    api_key,
    state,
    run_id,
    logger,
):
    started = time.perf_counter()

    cp = load_checkpoint(
        run_id,
        state,
    )

    # Batch artifacts under output/<run_id>/<state>/batches are the
    # persistence source of truth for 2E recovery.
    # The legacy single state-level CSV is intentionally not used here.

    # -----------------------------------------------------------------------
    # Already completed
    # -----------------------------------------------------------------------

    if cp.get("status") == "COMPLETED":

        logger.info(
            "STATE SKIPPED | "
            "State=%s | "
            "Status=COMPLETED | "
            "Records=%s",
            state,
            cp.get(
                "records_written",
                0,
            ),
        )

        return cp

    # -----------------------------------------------------------------------
    # Resume state
    # -----------------------------------------------------------------------

    offset = int(
        cp.get(
            "last_completed_offset",
            0,
        )
    )

    written = int(
        cp.get(
            "records_written",
            0,
        )
    )

    total = cp.get(
        "total_records"
    )

    # Resume is driven by the checkpoint plus the batch manifest/artifacts.
    # Do not reset progress merely because the legacy state-level CSV does
    # not exist; 2E writes deterministic per-batch files instead.

    cp.update(
        {
            "run_id": run_id,
            "state": state,
            "status": "IN_PROGRESS",
            "last_completed_offset": offset,
            "records_written": written,
            "total_records": total,
            "failure_reason": None,
            "failure_stage": None,
            "failure_detail": "",
            "retry_count": 0,
            "http_status": None,
            "failed_at": None,
        }
    )

    save_checkpoint(
        run_id,
        state,
        cp,
    )

    logger.info(
        "=" * 80
    )

    logger.info(
        "STATE STARTED | "
        "State=%s | "
        "RunID=%s | "
        "ResumeOffset=%s",
        state,
        run_id,
        offset,
    )

    logger.info(
        "=" * 80
    )

    # -----------------------------------------------------------------------
    # Batch loop
    # -----------------------------------------------------------------------

    while True:

        if is_shutdown_requested():
            return mark_state_failed(
                cp,
                run_id,
                state,
                logger,
                reason="SHUTDOWN_REQUESTED",
                stage="SHUTDOWN",
            )

        batch_start = time.perf_counter()

        # -------------------------------------------------------------------
        # 2D.2 - Recovery check
        #
        # Before calling the API, determine whether this exact
        # run/state/offset batch has already been persisted.
        # -------------------------------------------------------------------

        if is_shutdown_requested():
            return mark_state_failed(
                cp,
                run_id,
                state,
                logger,
                reason="SHUTDOWN_REQUESTED",
                stage="SHUTDOWN",
            )

        persisted_batch = get_persisted_batch(
            run_id,
            state,
            offset,
        )

        if persisted_batch is not None:

            batch_file = persisted_batch.get("batch_file")
            _, validation_reason = STORAGE.validate_artifact(
                persisted_batch,
                calculate_file_sha256,
            )

            if validation_reason:
                logger.error(
                    "BATCH ARTIFACT VALIDATION FAILED | "
                    "State=%s | "
                    "Offset=%s | "
                    "BatchID=%s | "
                    "Reason=%s | "
                    "BatchFile=%s",
                    state,
                    offset,
                    persisted_batch.get("batch_id"),
                    validation_reason,
                    batch_file,
                )

                return mark_state_failed(
                    cp,
                    run_id,
                    state,
                    logger,
                    reason="BATCH_ARTIFACT_INVALID",
                    stage="ARTIFACT_VALIDATION",
                    detail=validation_reason,
                )

            recovered_count = int(
                persisted_batch.get(
                    "record_count",
                    0,
                )
            )

            if recovered_count <= 0:

                logger.error(
                    "INVALID MANIFEST BATCH | "
                    "State=%s | "
                    "Offset=%s | "
                    "RecordCount=%s",
                    state,
                    offset,
                    recovered_count,
                )

                cp.update(
                    {
                        "status": "FAILED",
                        "last_completed_offset": offset,
                        "records_written": written,
                        "total_records": total,
                    }
                )

                save_checkpoint(
                    run_id,
                    state,
                    cp,
                )

                return cp

            # Recover the already persisted batch.
            written += recovered_count
            offset += recovered_count

            cp.update(
                {
                    "total_records": total,
                    "records_written": written,
                    "last_completed_offset": offset,
                    "status": "IN_PROGRESS",
                }
            )

            save_checkpoint(
                run_id,
                state,
                cp,
            )

            logger.warning(
                "BATCH RECOVERED | "
                "State=%s | "
                "BatchID=%s | "
                "RecoveredRecords=%s | "
                "Progress=%s/%s | "
                "NextOffset=%s | "
                "Elapsed=%s",
                state,
                persisted_batch.get(
                    "batch_id"
                ),
                recovered_count,
                written,
                total,
                offset,
                format_elapsed(
                    time.perf_counter()
                    - batch_start
                ),
            )

            # If recovery brought us to the known total,
            # reconcile before marking the state completed.
            if total is not None and written >= total:

                if not reconcile_state(
                    state=state,
                    total_records=total,
                    records_written=written,
                    logger=logger,
                ):
                    cp.update(
                        {
                            "status": "FAILED",
                            "total_records": total,
                            "records_written": written,
                            "last_completed_offset": offset,
                        }
                    )

                    save_checkpoint(
                        run_id,
                        state,
                        cp,
                    )

                    return cp

                cp.update(
                    {
                        "status": "COMPLETED",
                        "total_records": total,
                        "records_written": written,
                        "last_completed_offset": offset,
                    }
                )

                save_checkpoint(
                    run_id,
                    state,
                    cp,
                )

                logger.info(
                    "STATE COMPLETED AFTER RECOVERY | "
                    "State=%s | "
                    "Records=%s | "
                    "Elapsed=%s",
                    state,
                    written,
                    format_elapsed(
                        time.perf_counter()
                        - started
                    ),
                )

                return cp

            # Move to the next batch without calling the API
            # for the recovered batch.
            continue

        # -------------------------------------------------------------------
        # Fetch next batch
        # -------------------------------------------------------------------

        try:
            data = fetch_batch(
                api_key,
                state,
                offset,
                logger,
            )
        except ExtractionError as exc:
            return mark_state_failed(
                cp,
                run_id,
                state,
                logger,
                reason=exc.reason,
                stage=exc.stage,
                detail=exc.detail,
                retry_count=exc.retry_count,
                http_status=exc.http_status,
            )

        # -------------------------------------------------------------------
        # Capture total
        # -------------------------------------------------------------------

        if total is None:

            total = int(
                data.get("total")
                or 0
            )

        records = (
            data.get("records")
            or []
        )

        count = len(records)

        # -------------------------------------------------------------------
        # No records
        # -------------------------------------------------------------------

        if not records:

            if not reconcile_state(
                state=state,
                total_records=total,
                records_written=written,
                logger=logger,
            ):
                cp.update(
                    {
                        "status": "FAILED",
                        "total_records": total,
                        "records_written": written,
                        "last_completed_offset": offset,
                    }
                )

                save_checkpoint(
                    run_id,
                    state,
                    cp,
                )

                return cp

            cp.update(
                {
                    "status": "COMPLETED",
                    "total_records": total,
                    "records_written": written,
                    "last_completed_offset": offset,
                }
            )

            save_checkpoint(
                run_id,
                state,
                cp,
            )

            logger.info(
                "STATE COMPLETED | "
                "State=%s | "
                "Records=%s | "
                "Elapsed=%s",
                state,
                written,
                format_elapsed(
                    time.perf_counter()
                    - started
                ),
            )

            return cp

        # -------------------------------------------------------------------
        # Persist batch
        # -------------------------------------------------------------------

        batch_offset = offset

        if SETTINGS.storage_backend == "local":
            batch_file = batch_output_path(
                run_id,
                state,
                batch_offset,
            )

            # If the final artifact exists without a SUCCESS manifest, do not
            # overwrite it. Fail closed so the orphaned artifact can be inspected.
            if batch_file.exists():
                logger.error(
                    "BATCH ARTIFACT EXISTS WITHOUT MANIFEST | "
                    "State=%s | Offset=%s | BatchFile=%s",
                    state,
                    batch_offset,
                    batch_file,
                )
                return mark_state_failed(
                    cp,
                    run_id,
                    state,
                    logger,
                    reason="ORPHAN_BATCH_ARTIFACT",
                    stage="ARTIFACT_PERSISTENCE",
                    detail=str(batch_file),
                )
        else:
            staging_dir = OUTPUT_ROOT / run_id / ".staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            batch_file = staging_dir / f"{get_batch_id(run_id, state, batch_offset)}.csv"

        written_count = write_batch_file(batch_file, records)

        # Protect against an unexpected persistence count mismatch.
        if written_count != count:

            logger.error(
                "PERSISTENCE COUNT MISMATCH | "
                "State=%s | "
                "Offset=%s | "
                "Expected=%s | "
                "Written=%s",
                state,
                batch_offset,
                count,
                written_count,
            )

            cp.update(
                {
                    "status": "FAILED",
                    "last_completed_offset": offset,
                    "records_written": written,
                    "total_records": total,
                }
            )

            save_checkpoint(
                run_id,
                state,
                cp,
            )

            return cp

        # -------------------------------------------------------------------
        # Publish the batch to the configured RAW storage backend.
        # -------------------------------------------------------------------

        checksum = calculate_file_sha256(batch_file)

        try:
            persisted_batch_file = STORAGE.publish_batch(
                batch_file,
                run_id,
                state,
                batch_offset,
                checksum,
            )
        except StorageError as exc:
            return mark_state_failed(
                cp,
                run_id,
                state,
                logger,
                reason="STORAGE_UPLOAD_FAILED",
                stage="RAW_PERSISTENCE",
                detail=str(exc),
            )
        finally:
            if SETTINGS.storage_backend == "gcs":
                try:
                    batch_file.unlink(missing_ok=True)
                except OSError:
                    pass

        # -------------------------------------------------------------------
        # Update counters
        # -------------------------------------------------------------------

        written += written_count
        offset += written_count

        # -------------------------------------------------------------------
        # Manifest persistence
        #
        # Ordering:
        #
        #     CSV
        #       ↓
        #     SHA-256 checksum
        #       ↓
        #     Manifest
        #       ↓
        #     Checkpoint
        #
        # A SUCCESS manifest entry therefore means the CSV batch
        # has already been written and its checksum has been recorded.
        # -------------------------------------------------------------------

        write_batch_manifest(
            run_id=run_id,
            state=state,
            offset=batch_offset,
            record_count=written_count,
            batch_path=persisted_batch_file,
            checksum=checksum,
            status="SUCCESS",
        )

        # -------------------------------------------------------------------
        # Checkpoint
        # -------------------------------------------------------------------

        cp.update(
            {
                "total_records": total,
                "records_written": written,
                "last_completed_offset": offset,
                "status": "IN_PROGRESS",
            }
        )

        save_checkpoint(
            run_id,
            state,
            cp,
        )

        # -------------------------------------------------------------------
        # Batch logging
        # -------------------------------------------------------------------

        logger.info(
            "BATCH COMPLETE | "
            "State=%s | "
            "BatchID=%s | "
            "BatchRecords=%s | "
            "Progress=%s/%s | "
            "Offset=%s | "
            "BatchElapsed=%s",
            state,
            get_batch_id(
                run_id,
                state,
                batch_offset,
            ),
            written_count,
            written,
            total,
            offset,
            format_elapsed(
                time.perf_counter()
                - batch_start
            ),
        )

        # -------------------------------------------------------------------
        # State completion
        # -------------------------------------------------------------------

        if (
            total is not None
            and written >= total
        ) or (
            total is not None
            and count < BATCH_SIZE
        ):

            if not reconcile_state(
                state=state,
                total_records=total,
                records_written=written,
                logger=logger,
            ):
                cp.update(
                    {
                        "status": "FAILED",
                        "total_records": total,
                        "records_written": written,
                        "last_completed_offset": offset,
                    }
                )

                save_checkpoint(
                    run_id,
                    state,
                    cp,
                )

                return cp

            cp.update(
                {
                    "status": "COMPLETED",
                    "total_records": total,
                    "records_written": written,
                    "last_completed_offset": offset,
                }
            )

            save_checkpoint(
                run_id,
                state,
                cp,
            )

            logger.info(
                "STATE COMPLETED | "
                "State=%s | "
                "Records=%s | "
                "Elapsed=%s",
                state,
                written,
                format_elapsed(
                    time.perf_counter()
                    - started
                ),
            )

            return cp


# ---------------------------------------------------------------------------
# Parallel state extraction
# ---------------------------------------------------------------------------

def extract_states(
    api_key,
    states,
    run_id,
    logger,
    max_workers=3,
):
    from concurrent.futures import (
        ThreadPoolExecutor,
        as_completed,
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {
            executor.submit(
                extract_state,
                api_key,
                state,
                run_id,
                logger,
            ): state
            for state in states
        }

        for future in as_completed(
            futures
        ):

            state = futures[future]

            try:

                results.append(
                    future.result()
                )

            except Exception as exc:

                logger.exception(
                    "UNHANDLED STATE ERROR | "
                    "State=%s | "
                    "Error=%s",
                    state,
                    exc,
                )

                cp = load_checkpoint(run_id, state)
                results.append(
                    mark_state_failed(
                        cp,
                        run_id,
                        state,
                        logger,
                        reason="UNHANDLED_EXCEPTION",
                        stage="STATE_EXTRACTION",
                        detail=str(exc),
                    )
                )

    return results