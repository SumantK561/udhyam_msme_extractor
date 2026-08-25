import os
import csv
import json
import subprocess
import logging
import time
import random
from datetime import datetime
from urllib.parse import urlencode

from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# CONFIGURATION
# =========================================================

API_KEY = os.getenv("UDYAM_API_KEY")

RESOURCE_ID = "8b68ae56-84cf-4728-a0a6-1be11028dea7"

BASE_URL = (
    f"https://api.data.gov.in/resource/{RESOURCE_ID}"
)

OUTPUT_ROOT = "output"
CHECKPOINT_ROOT = "checkpoints"

BATCH_SIZE = 10000

MAX_RETRIES = 5

CONNECT_TIMEOUT = 30

MAX_REQUEST_TIME = 300

RETRY_BASE_SECONDS = 10


# =========================================================
# LOGGER
# =========================================================

logger = logging.getLogger("udyam")


# =========================================================
# CSV HEADERS
# =========================================================

CSV_HEADERS = [
    "LG_ST_Code",
    "State",
    "LG_DT_Code",
    "District",
    "Pincode",
    "RegistrationDate",
    "EnterpriseName",
    "CommunicationAddress",
    "Activities"
]


# =========================================================
# TIME FORMAT
# =========================================================

def format_elapsed(seconds):
    """
    Convert seconds into HH:MM:SS.
    """

    seconds = int(seconds)

    hours, remainder = divmod(
        seconds,
        3600
    )

    minutes, seconds = divmod(
        remainder,
        60
    )

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d}"
    )


# =========================================================
# MONTH / RUN DIRECTORIES
# =========================================================

def get_output_dir(run_id):

    directory = os.path.join(
        OUTPUT_ROOT,
        run_id
    )

    os.makedirs(
        directory,
        exist_ok=True
    )

    return directory


def get_checkpoint_dir(run_id):

    directory = os.path.join(
        CHECKPOINT_ROOT,
        run_id
    )

    os.makedirs(
        directory,
        exist_ok=True
    )

    return directory


# =========================================================
# FILE PATHS
# =========================================================

def get_output_file(
    run_id,
    state,
    district
):

    output_dir = get_output_dir(
        run_id
    )

    return os.path.join(
        output_dir,
        f"udyam_msme_{state}_{district}.csv"
    )


def get_checkpoint_file(
    run_id,
    state,
    district
):

    checkpoint_dir = get_checkpoint_dir(
        run_id
    )

    return os.path.join(
        checkpoint_dir,
        f"{state}_{district}.json"
    )


# =========================================================
# CHECKPOINT
# =========================================================

def load_checkpoint(
    run_id,
    state,
    district
):

    checkpoint_file = get_checkpoint_file(
        run_id,
        state,
        district
    )

    if not os.path.exists(
        checkpoint_file
    ):
        return None

    try:

        with open(
            checkpoint_file,
            "r",
            encoding="utf-8"
        ) as file:

            checkpoint = json.load(
                file
            )

        # Extra safety: checkpoint must belong
        # to the current monthly run.
        if checkpoint.get(
            "run_id"
        ) != run_id:

            logger.warning(
                "Checkpoint run_id mismatch | "
                "Expected=%s | Found=%s",
                run_id,
                checkpoint.get("run_id")
            )

            return None

        return checkpoint

    except Exception:

        logger.exception(
            "Failed to read checkpoint | "
            "Run=%s | "
            "State=%s | "
            "District=%s",
            run_id,
            state,
            district
        )

        return None


def save_checkpoint(
    run_id,
    state,
    district,
    total_records,
    records_written,
    last_completed_offset,
    status
):

    checkpoint_file = get_checkpoint_file(
        run_id,
        state,
        district
    )

    checkpoint = {
        "run_id": run_id,
        "state": state,
        "district": district,
        "total_records": total_records,
        "records_written": records_written,
        "last_completed_offset": last_completed_offset,
        "status": status,
        "updated_at": datetime.now().isoformat()
    }

    temp_file = (
        checkpoint_file + ".tmp"
    )

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                checkpoint,
                file,
                indent=4
            )

        # Atomic replacement
        os.replace(
            temp_file,
            checkpoint_file
        )

    except Exception:

        logger.exception(
            "Failed to save checkpoint | "
            "Run=%s | "
            "State=%s | "
            "District=%s",
            run_id,
            state,
            district
        )

        if os.path.exists(
            temp_file
        ):

            try:
                os.remove(
                    temp_file
                )
            except OSError:
                pass

        raise


# =========================================================
# API URL
# =========================================================

def build_api_url(
    state,
    district,
    offset,
    limit
):

    params = {
        "api-key": API_KEY,
        "format": "json",
        "offset": offset,
        "limit": limit,
        "filters[State]": state,
        "filters[District]": district
    }

    return (
        BASE_URL
        + "?"
        + urlencode(params)
    )


# =========================================================
# API REQUEST
# =========================================================

def get_udyam_data(
    state,
    district,
    offset=0,
    limit=BATCH_SIZE
):

    if not API_KEY:

        logger.error(
            "UDYAM_API_KEY is not configured."
        )

        return None

    url = build_api_url(
        state,
        district,
        offset,
        limit
    )

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        logger.info(
            "API REQUEST | "
            "State=%s | "
            "District=%s | "
            "Offset=%s | "
            "Limit=%s | "
            "Attempt=%s/%s",
            state,
            district,
            offset,
            limit,
            attempt,
            MAX_RETRIES
        )

        command = [
            "curl.exe",
            "-s",
            "--connect-timeout",
            str(CONNECT_TIMEOUT),
            "--max-time",
            str(MAX_REQUEST_TIME),
            "-H",
            "accept: application/json",
            url
        ]

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            # -------------------------------------------------
            # SUCCESS
            # -------------------------------------------------

            if result.returncode == 0:

                try:

                    data = json.loads(
                        result.stdout
                    )

                except json.JSONDecodeError:

                    logger.warning(
                        "Invalid JSON response | "
                        "State=%s | "
                        "District=%s | "
                        "Offset=%s | "
                        "Attempt=%s/%s",
                        state,
                        district,
                        offset,
                        attempt,
                        MAX_RETRIES
                    )

                    continue

                records = data.get(
                    "records",
                    []
                )

                logger.info(
                    "API SUCCESS | "
                    "State=%s | "
                    "District=%s | "
                    "Offset=%s | "
                    "Records=%s",
                    state,
                    district,
                    offset,
                    len(records)
                )

                return data

            # -------------------------------------------------
            # TIMEOUT
            # -------------------------------------------------

            if result.returncode == 28:

                logger.warning(
                    "API TIMEOUT | "
                    "State=%s | "
                    "District=%s | "
                    "Offset=%s | "
                    "Attempt=%s/%s",
                    state,
                    district,
                    offset,
                    attempt,
                    MAX_RETRIES
                )

            else:

                logger.warning(
                    "CURL FAILURE | "
                    "ReturnCode=%s | "
                    "State=%s | "
                    "District=%s | "
                    "Offset=%s | "
                    "Attempt=%s/%s",
                    result.returncode,
                    state,
                    district,
                    offset,
                    attempt,
                    MAX_RETRIES
                )

                if result.stderr:

                    logger.warning(
                        "curl stderr: %s",
                        result.stderr.strip()
                    )

        except Exception:

            logger.exception(
                "Unexpected API exception | "
                "State=%s | "
                "District=%s | "
                "Offset=%s | "
                "Attempt=%s/%s",
                state,
                district,
                offset,
                attempt,
                MAX_RETRIES
            )

        # -----------------------------------------------------
        # RETRY
        # -----------------------------------------------------

        if attempt < MAX_RETRIES:

            backoff = (
                RETRY_BASE_SECONDS
                * (2 ** (attempt - 1))
            )

            jitter = random.uniform(
                0,
                5
            )

            wait_seconds = (
                backoff + jitter
            )

            logger.info(
                "RETRY WAIT | "
                "State=%s | "
                "District=%s | "
                "Offset=%s | "
                "Wait=%.1f seconds",
                state,
                district,
                offset,
                wait_seconds
            )

            time.sleep(
                wait_seconds
            )

    logger.error(
        "API FAILED AFTER RETRIES | "
        "State=%s | "
        "District=%s | "
        "Offset=%s",
        state,
        district,
        offset
    )

    return None


# =========================================================
# CSV WRITER
# =========================================================

def write_batch_to_csv(
    records,
    output_file,
    write_header=False
):

    if not records:

        return 0

    with open(
        output_file,
        "a",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=CSV_HEADERS,
            extrasaction="ignore"
        )

        if write_header:

            writer.writeheader()

        writer.writerows(
            records
        )

    return len(records)


# =========================================================
# EXTRACT ONE DISTRICT
# =========================================================

def extract_district(
    run_id,
    state,
    district
):

    start_time = time.perf_counter()

    logger.info("=" * 90)

    logger.info(
        "DISTRICT STARTED | "
        "Run=%s | "
        "State=%s | "
        "District=%s",
        run_id,
        state,
        district
    )

    logger.info("=" * 90)

    output_file = get_output_file(
        run_id,
        state,
        district
    )

    checkpoint = load_checkpoint(
        run_id,
        state,
        district
    )

    # =====================================================
    # ALREADY COMPLETED THIS MONTH
    # =====================================================

    if checkpoint:

        if checkpoint.get(
            "status"
        ) == "COMPLETED":

            elapsed = (
                time.perf_counter()
                - start_time
            )

            logger.info(
                "DISTRICT SKIPPED | "
                "Run=%s | "
                "State=%s | "
                "District=%s | "
                "Reason=COMPLETED_THIS_RUN | "
                "Records=%s",
                run_id,
                state,
                district,
                checkpoint.get(
                    "records_written",
                    0
                )
            )

            return {
                "state": state,
                "district": district,
                "status": "SKIPPED",
                "records": checkpoint.get(
                    "records_written",
                    0
                ),
                "elapsed": elapsed
            }

    # =====================================================
    # RESUME INFORMATION
    # =====================================================

    offset = 0
    total_written = 0
    total = 0

    if checkpoint:

        offset = checkpoint.get(
            "last_completed_offset",
            0
        )

        total_written = checkpoint.get(
            "records_written",
            0
        )

        total = checkpoint.get(
            "total_records",
            0
        )

        logger.info(
            "RESUME | "
            "Run=%s | "
            "State=%s | "
            "District=%s | "
            "Offset=%s | "
            "Records=%s | "
            "Total=%s",
            run_id,
            state,
            district,
            offset,
            total_written,
            total
        )

        # If checkpoint exists but CSV is gone,
        # restart safely.
        if not os.path.exists(
            output_file
        ):

            logger.warning(
                "Checkpoint exists but CSV is missing. "
                "Restarting district from offset 0."
            )

            offset = 0
            total_written = 0
            total = 0

    else:

        # New monthly run, no checkpoint.
        #
        # If a CSV somehow exists without a checkpoint,
        # don't append to potentially stale data.
        if os.path.exists(
            output_file
        ):

            logger.warning(
                "CSV exists without checkpoint. "
                "Removing stale CSV."
            )

            os.remove(
                output_file
            )

    # =====================================================
    # FIRST / RESUME API REQUEST
    # =====================================================

    data = get_udyam_data(
        state=state,
        district=district,
        offset=offset,
        limit=BATCH_SIZE
    )

    if not data:

        elapsed = (
            time.perf_counter()
            - start_time
        )

        logger.error(
            "DISTRICT FAILED | "
            "Run=%s | "
            "State=%s | "
            "District=%s | "
            "Offset=%s | "
            "Elapsed=%s",
            run_id,
            state,
            district,
            offset,
            format_elapsed(elapsed)
        )

        save_checkpoint(
            run_id,
            state,
            district,
            total,
            total_written,
            offset,
            "FAILED"
        )

        return {
            "state": state,
            "district": district,
            "status": "FAILED",
            "records": total_written,
            "elapsed": elapsed
        }

    # =====================================================
    # TOTAL RECORD COUNT
    # =====================================================

    if total == 0:

        try:

            total = int(
                data.get(
                    "total",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            total = 0

        logger.info(
            "TOTAL RECORDS | "
            "Run=%s | "
            "State=%s | "
            "District=%s | "
            "Total=%s",
            run_id,
            state,
            district,
            total
        )

    # =====================================================
    # ZERO RECORD DISTRICT
    # =====================================================

    if total == 0:

        elapsed = (
            time.perf_counter()
            - start_time
        )

        save_checkpoint(
            run_id,
            state,
            district,
            0,
            0,
            0,
            "COMPLETED"
        )

        logger.info(
            "DISTRICT COMPLETED | "
            "State=%s | "
            "District=%s | "
            "Records=0 | "
            "Elapsed=%s",
            state,
            district,
            format_elapsed(elapsed)
        )

        return {
            "state": state,
            "district": district,
            "status": "SUCCESS",
            "records": 0,
            "elapsed": elapsed
        }

    # =====================================================
    # PAGINATION
    # =====================================================

    batch_number = (
        (offset // BATCH_SIZE)
        + 1
    )

    while offset < total:

        batch_start = time.perf_counter()

        records = data.get(
            "records",
            []
        )

        if not records:

            elapsed = (
                time.perf_counter()
                - start_time
            )

            logger.error(
                "EMPTY BATCH | "
                "State=%s | "
                "District=%s | "
                "Offset=%s",
                state,
                district,
                offset
            )

            save_checkpoint(
                run_id,
                state,
                district,
                total,
                total_written,
                offset,
                "FAILED"
            )

            return {
                "state": state,
                "district": district,
                "status": "FAILED",
                "records": total_written,
                "elapsed": elapsed
            }

        # -------------------------------------------------
        # WRITE CSV
        # -------------------------------------------------

        write_header = (
            offset == 0
        )

        records_in_batch = write_batch_to_csv(
            records,
            output_file,
            write_header
        )

        total_written += records_in_batch

        offset += records_in_batch

        batch_elapsed = (
            time.perf_counter()
            - batch_start
        )

        logger.info(
            "BATCH COMPLETE | "
            "State=%s | "
            "District=%s | "
            "Batch=%s | "
            "BatchRecords=%s | "
            "Progress=%s/%s | "
            "BatchElapsed=%s",
            state,
            district,
            batch_number,
            records_in_batch,
            total_written,
            total,
            format_elapsed(batch_elapsed)
        )

        # -------------------------------------------------
        # CHECKPOINT AFTER CSV WRITE
        # -------------------------------------------------

        save_checkpoint(
            run_id,
            state,
            district,
            total,
            total_written,
            offset,
            "IN_PROGRESS"
        )

        # -------------------------------------------------
        # SAFETY
        # -------------------------------------------------

        if records_in_batch <= 0:

            elapsed = (
                time.perf_counter()
                - start_time
            )

            logger.error(
                "ZERO RECORD BATCH | "
                "State=%s | "
                "District=%s | "
                "Offset=%s",
                state,
                district,
                offset
            )

            save_checkpoint(
                run_id,
                state,
                district,
                total,
                total_written,
                offset,
                "FAILED"
            )

            return {
                "state": state,
                "district": district,
                "status": "FAILED",
                "records": total_written,
                "elapsed": elapsed
            }

        # -------------------------------------------------
        # NEXT BATCH
        # -------------------------------------------------

        if offset < total:

            batch_number += 1

            data = get_udyam_data(
                state=state,
                district=district,
                offset=offset,
                limit=BATCH_SIZE
            )

            if not data:

                elapsed = (
                    time.perf_counter()
                    - start_time
                )

                logger.error(
                    "NEXT BATCH FAILED | "
                    "State=%s | "
                    "District=%s | "
                    "Offset=%s | "
                    "Elapsed=%s",
                    state,
                    district,
                    offset,
                    format_elapsed(elapsed)
                )

                save_checkpoint(
                    run_id,
                    state,
                    district,
                    total,
                    total_written,
                    offset,
                    "FAILED"
                )

                return {
                    "state": state,
                    "district": district,
                    "status": "FAILED",
                    "records": total_written,
                    "elapsed": elapsed
                }

    # =====================================================
    # FINAL VALIDATION
    # =====================================================

    elapsed = (
        time.perf_counter()
        - start_time
    )

    logger.info(
        "VALIDATION | "
        "State=%s | "
        "District=%s | "
        "Expected=%s | "
        "Written=%s",
        state,
        district,
        total,
        total_written
    )

    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    if total_written == total:

        save_checkpoint(
            run_id,
            state,
            district,
            total,
            total_written,
            offset,
            "COMPLETED"
        )

        logger.info(
            "DISTRICT COMPLETED | "
            "Run=%s | "
            "State=%s | "
            "District=%s | "
            "Records=%s | "
            "Elapsed=%s",
            run_id,
            state,
            district,
            total_written,
            format_elapsed(elapsed)
        )

        return {
            "state": state,
            "district": district,
            "status": "SUCCESS",
            "records": total_written,
            "elapsed": elapsed
        }

    # -----------------------------------------------------
    # COUNT MISMATCH
    # -----------------------------------------------------

    logger.error(
        "RECORD COUNT MISMATCH | "
        "State=%s | "
        "District=%s | "
        "Expected=%s | "
        "Written=%s | "
        "Elapsed=%s",
        state,
        district,
        total,
        total_written,
        format_elapsed(elapsed)
    )

    save_checkpoint(
        run_id,
        state,
        district,
        total,
        total_written,
        offset,
        "FAILED"
    )

    return {
        "state": state,
        "district": district,
        "status": "FAILED",
        "records": total_written,
        "elapsed": elapsed
    }


# =========================================================
# MODULE ENTRY
# =========================================================

if __name__ == "__main__":

    print(
        "Run this module using run_udyam.py"
    )