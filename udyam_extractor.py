# Udyam MSME State-level extractor

import csv
import json
import os
import random
import subprocess
import tempfile
import time
import threading

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


BASE_URL = (
    "https://api.data.gov.in/resource/"
    "8b68ae56-84cf-4728-a0a6-1be11028dea7"
)

BATCH_SIZE = 10000
MAX_RETRIES = 5
CONNECT_TIMEOUT = 30
MAX_REQUEST_TIME = 300

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


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logger():
    import logging

    LOG_ROOT.mkdir(parents=True, exist_ok=True)

    path = LOG_ROOT / (
        f"udyam_{datetime.now():%Y%m%d_%H%M%S}.log"
    )

    logger = logging.getLogger("udyam")
    logger.setLevel(logging.INFO)
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

    if expected != actual:
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
    """Verify the manifest's physical batch artifact exists and is non-empty."""

    batch_file = manifest_record.get("batch_file")

    if not batch_file:
        return False

    path = Path(batch_file)

    try:
        return (
            path.exists()
            and path.is_file()
            and path.stat().st_size > 0
        )
    except OSError:
        return False


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

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        temp_path = None
        started = time.perf_counter()

        try:

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".json",
            ) as file:

                temp_path = file.name

            cmd = [
                "curl.exe",
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
                url,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            elapsed = (
                time.perf_counter()
                - started
            )

            if result.returncode:

                logger.error(
                    "CURL FAILURE | "
                    "State=%s | "
                    "Offset=%s | "
                    "ReturnCode=%s | "
                    "Elapsed=%s | "
                    "Error=%s",
                    state,
                    offset,
                    result.returncode,
                    format_elapsed(elapsed),
                    result.stderr.strip(),
                )

            else:

                try:

                    data = json.loads(
                        Path(
                            temp_path
                        ).read_text(
                            encoding="utf-8"
                        )
                    )

                    if data.get("status") == "ok":

                        records = (
                            data.get("records")
                            or []
                        )

                        count = len(records)

                        total = int(
                            data.get("total")
                            or 0
                        )

                        logger.info(
                            "API RESPONSE | "
                            "State=%s | "
                            "Offset=%s | "
                            "Count=%s | "
                            "Total=%s | "
                            "Elapsed=%s",
                            state,
                            offset,
                            count,
                            total,
                            format_elapsed(
                                elapsed
                            ),
                        )

                        # -------------------------------------------------------------------
                        # Short-page protection
                        # -------------------------------------------------------------------
                        #
                        # A page smaller than BATCH_SIZE is only valid when it
                        # reaches the end of the dataset. If more records remain,
                        # retry the exact same offset instead of advancing.
                        # -------------------------------------------------------------------

                        if (
                            count < BATCH_SIZE
                            and offset + count < total
                        ):

                            logger.warning(
                                "SHORT API PAGE | "
                                "State=%s | "
                                "Offset=%s | "
                                "Count=%s | "
                                "Total=%s | "
                                "ExpectedAtLeast=%s | "
                                "RetryingSameOffset",
                                state,
                                offset,
                                count,
                                total,
                                BATCH_SIZE,
                            )

                            continue

                        return data

                    logger.error(
                        "API ERROR | "
                        "State=%s | "
                        "Offset=%s | "
                        "Response=%s",
                        state,
                        offset,
                        json.dumps(data)[:1000],
                    )

                except (
                    json.JSONDecodeError,
                    OSError,
                ) as exc:

                    logger.error(
                        "INVALID API RESPONSE | "
                        "State=%s | "
                        "Offset=%s | "
                        "Error=%s",
                        state,
                        offset,
                        exc,
                    )

        finally:

            if temp_path:

                try:
                    os.remove(
                        temp_path
                    )

                except OSError:
                    pass

        if attempt < MAX_RETRIES:

            delay = (
                min(
                    60,
                    5 * (
                        2 ** (
                            attempt - 1
                        )
                    ),
                )
                + random.uniform(0, 3)
            )

            logger.warning(
                "RETRYING | "
                "State=%s | "
                "Offset=%s | "
                "RetryIn=%.1f seconds",
                state,
                offset,
                delay,
            )

            time.sleep(delay)

    logger.error(
        "API REQUEST FAILED AFTER RETRIES | "
        "State=%s | "
        "Offset=%s",
        state,
        offset,
    )

    return None


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

        batch_start = time.perf_counter()

        # -------------------------------------------------------------------
        # 2D.2 - Recovery check
        #
        # Before calling the API, determine whether this exact
        # run/state/offset batch has already been persisted.
        # -------------------------------------------------------------------

        persisted_batch = get_persisted_batch(
            run_id,
            state,
            offset,
        )

        if persisted_batch is not None:

            if not is_batch_artifact_valid(
                persisted_batch
            ):
                logger.error(
                    "MANIFEST ARTIFACT MISSING | "
                    "State=%s | "
                    "Offset=%s | "
                    "BatchID=%s | "
                    "BatchFile=%s",
                    state,
                    offset,
                    persisted_batch.get("batch_id"),
                    persisted_batch.get("batch_file"),
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

        data = fetch_batch(
            api_key,
            state,
            offset,
            logger,
        )

        if data is None:

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

            logger.error(
                "STATE FAILED | "
                "State=%s | "
                "RecordsWritten=%s | "
                "LastCompletedOffset=%s | "
                "Elapsed=%s",
                state,
                written,
                offset,
                format_elapsed(
                    time.perf_counter()
                    - started
                ),
            )

            return cp

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
                "State=%s | "
                "Offset=%s | "
                "BatchFile=%s",
                state,
                batch_offset,
                batch_file,
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

        written_count = write_batch_file(
            batch_file,
            records,
        )

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
        #     Manifest
        #       ↓
        #     Checkpoint
        #
        # A SUCCESS manifest entry therefore means the CSV batch
        # has already been written.
        # -------------------------------------------------------------------

        write_batch_manifest(
            run_id=run_id,
            state=state,
            offset=batch_offset,
            record_count=written_count,
            batch_path=batch_file,
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

                results.append(
                    {
                        "state": state,
                        "status": "FAILED",
                        "records_written": 0,
                    }
                )

    return results