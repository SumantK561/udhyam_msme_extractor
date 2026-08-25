import os
import json
import logging
import time
from datetime import datetime
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

from dotenv import load_dotenv

from udyam_extractor import (
    extract_district,
    load_checkpoint,
    format_elapsed
)


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# CONFIGURATION
# =========================================================

MASTER_FILE = "udyam_state_district.json"

LOG_DIR = "logs"


# ---------------------------------------------------------
# MONTHLY RUN ID
#
# Example:
#
# August 2026  -> 2026-08-01
# September 2026 -> 2026-09-01
#
# IMPORTANT:
#
# Re-running during the same month resumes/skips.
# Next month automatically starts a new run.
# ---------------------------------------------------------

RUN_ID = datetime.now().strftime(
    "%Y-%m-%d"
)


# ---------------------------------------------------------
# STATE FILTER
#
# "BIHAR"        -> Bihar only
# "MAHARASHTRA"  -> Maharashtra only
# None           -> ALL STATES
# ---------------------------------------------------------

TEST_STATE = "BIHAR"


# ---------------------------------------------------------
# PARALLEL WORKERS
#
# Start with 3.
# ---------------------------------------------------------

MAX_WORKERS = 3


# =========================================================
# LOG DIRECTORY
# =========================================================

os.makedirs(
    LOG_DIR,
    exist_ok=True
)


# =========================================================
# LOGGING
# =========================================================

execution_start_datetime = datetime.now()

execution_start = time.perf_counter()

execution_timestamp = (
    execution_start_datetime.strftime(
        "%Y%m%d_%H%M%S"
    )
)

LOG_FILE = os.path.join(
    LOG_DIR,
    f"udyam_master_{execution_timestamp}.log"
)


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(threadName)s | "
        "%(message)s"
    ),
    handlers=[
        logging.FileHandler(
            LOG_FILE,
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)


logger = logging.getLogger("udyam")


# =========================================================
# LOAD MASTER
# =========================================================

def load_state_district_master():

    if not os.path.exists(
        MASTER_FILE
    ):

        logger.error(
            "Master file not found: %s",
            MASTER_FILE
        )

        raise FileNotFoundError(
            MASTER_FILE
        )

    with open(
        MASTER_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(
            file
        )


# =========================================================
# PROCESS ONE DISTRICT
# =========================================================

def process_district(
    state_name,
    district_name
):

    logger.info(
        "DISTRICT QUEUED | "
        "Run=%s | "
        "State=%s | "
        "District=%s",
        RUN_ID,
        state_name,
        district_name
    )

    # -----------------------------------------------------
    # Check current month's checkpoint
    # -----------------------------------------------------

    checkpoint = load_checkpoint(
        RUN_ID,
        state_name,
        district_name
    )

    if checkpoint:

        if checkpoint.get(
            "status"
        ) == "COMPLETED":

            logger.info(
                "DISTRICT SKIPPED | "
                "Run=%s | "
                "State=%s | "
                "District=%s | "
                "Reason=COMPLETED_THIS_MONTH",
                RUN_ID,
                state_name,
                district_name
            )

            return {
                "state": state_name,
                "district": district_name,
                "status": "SKIPPED",
                "records": checkpoint.get(
                    "records_written",
                    0
                ),
                "elapsed": 0
            }

    # -----------------------------------------------------
    # Extract
    # -----------------------------------------------------

    return extract_district(
        run_id=RUN_ID,
        state=state_name,
        district=district_name
    )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info("=" * 100)

    logger.info(
        "UDYAM MASTER EXTRACTION STARTED"
    )

    logger.info(
        "Run ID              : %s",
        RUN_ID
    )

    logger.info(
        "Execution started   : %s",
        execution_start_datetime.isoformat()
    )

    logger.info(
        "Parallel workers    : %s",
        MAX_WORKERS
    )

    logger.info(
        "State filter        : %s",
        TEST_STATE if TEST_STATE else "ALL STATES"
    )

    logger.info(
        "Batch size           : 10000"
    )

    logger.info("=" * 100)

    # =====================================================
    # LOAD MASTER
    # =====================================================

    data = load_state_district_master()

    states = data.get(
        "states",
        []
    )

    # =====================================================
    # STATE FILTER
    # =====================================================

    if TEST_STATE:

        states = [
            state
            for state in states
            if state.get(
                "state",
                ""
            ).strip().upper()
            == TEST_STATE.strip().upper()
        ]

        if not states:

            logger.error(
                "State not found in master file: %s",
                TEST_STATE
            )

            return

        logger.info(
            "TEST MODE ENABLED | "
            "State=%s",
            TEST_STATE
        )

    else:

        logger.info(
            "FULL PRODUCTION MODE | "
            "All states enabled"
        )

    # =====================================================
    # TOTALS
    # =====================================================

    total_states = len(
        states
    )

    total_districts = sum(
        len(
            state.get(
                "districts",
                []
            )
        )
        for state in states
    )

    logger.info(
        "States to process     : %s",
        total_states
    )

    logger.info(
        "Districts to process  : %s",
        total_districts
    )

    # =====================================================
    # GLOBAL COUNTERS
    # =====================================================

    total_successful = 0
    total_skipped = 0
    total_failed = 0
    total_records = 0

    # =====================================================
    # STATE LOOP
    # =====================================================

    for state_index, state_data in enumerate(
        states,
        start=1
    ):

        state_name = state_data.get(
            "state",
            ""
        ).strip()

        districts = state_data.get(
            "districts",
            []
        )

        state_start = time.perf_counter()

        state_successful = 0
        state_skipped = 0
        state_failed = 0
        state_records = 0

        logger.info("")
        logger.info("=" * 100)

        logger.info(
            "STATE STARTED | "
            "Run=%s | "
            "State=%s | "
            "StateProgress=%s/%s | "
            "Districts=%s",
            RUN_ID,
            state_name,
            state_index,
            total_states,
            len(districts)
        )

        logger.info("=" * 100)

        # =================================================
        # PARALLEL DISTRICT PROCESSING
        # =================================================

        with ThreadPoolExecutor(
            max_workers=MAX_WORKERS,
            thread_name_prefix="UdyamWorker"
        ) as executor:

            futures = {}

            for district_data in districts:

                district_name = district_data.get(
                    "value",
                    ""
                ).strip()

                if not district_name:

                    logger.warning(
                        "Invalid district entry "
                        "in state %s",
                        state_name
                    )

                    continue

                future = executor.submit(
                    process_district,
                    state_name,
                    district_name
                )

                futures[
                    future
                ] = district_name

            completed_districts = 0

            # -------------------------------------------------
            # Process results as workers finish
            # -------------------------------------------------

            for future in as_completed(
                futures
            ):

                district_name = futures[
                    future
                ]

                completed_districts += 1

                try:

                    result = future.result()

                except Exception:

                    state_failed += 1

                    logger.exception(
                        "DISTRICT UNHANDLED EXCEPTION | "
                        "State=%s | "
                        "District=%s",
                        state_name,
                        district_name
                    )

                    continue

                status = result.get(
                    "status",
                    "FAILED"
                )

                records = result.get(
                    "records",
                    0
                )

                elapsed = result.get(
                    "elapsed",
                    0
                )

                state_records += records

                if status == "SUCCESS":

                    state_successful += 1

                elif status == "SKIPPED":

                    state_skipped += 1

                else:

                    state_failed += 1

                logger.info(
                    "DISTRICT RESULT | "
                    "Run=%s | "
                    "State=%s | "
                    "District=%s | "
                    "Status=%s | "
                    "Records=%s | "
                    "Elapsed=%s | "
                    "StateProgress=%s/%s",
                    RUN_ID,
                    state_name,
                    district_name,
                    status,
                    records,
                    format_elapsed(elapsed),
                    completed_districts,
                    len(futures)
                )

        # =================================================
        # STATE COMPLETE
        # =================================================

        state_elapsed = (
            time.perf_counter()
            - state_start
        )

        total_successful += (
            state_successful
        )

        total_skipped += (
            state_skipped
        )

        total_failed += (
            state_failed
        )

        total_records += (
            state_records
        )

        logger.info("")
        logger.info("=" * 100)

        logger.info(
            "STATE COMPLETED"
        )

        logger.info(
            "Run ID              : %s",
            RUN_ID
        )

        logger.info(
            "State               : %s",
            state_name
        )

        logger.info(
            "State elapsed time  : %s",
            format_elapsed(
                state_elapsed
            )
        )

        logger.info(
            "Districts           : %s",
            len(districts)
        )

        logger.info(
            "Successful          : %s",
            state_successful
        )

        logger.info(
            "Skipped             : %s",
            state_skipped
        )

        logger.info(
            "Failed              : %s",
            state_failed
        )

        logger.info(
            "Records             : %s",
            state_records
        )

        logger.info("=" * 100)

        # =================================================
        # OVERALL PROGRESS
        # =================================================

        overall_elapsed = (
            time.perf_counter()
            - execution_start
        )

        logger.info(
            "OVERALL PROGRESS | "
            "Run=%s | "
            "States=%s/%s | "
            "Successful=%s | "
            "Skipped=%s | "
            "Failed=%s | "
            "Records=%s | "
            "Elapsed=%s",
            RUN_ID,
            state_index,
            total_states,
            total_successful,
            total_skipped,
            total_failed,
            total_records,
            format_elapsed(
                overall_elapsed
            )
        )

    # =====================================================
    # FINAL SUMMARY
    # =====================================================

    overall_elapsed = (
        time.perf_counter()
        - execution_start
    )

    logger.info("")
    logger.info("=" * 100)

    logger.info(
        "UDYAM MASTER EXTRACTION FINISHED"
    )

    logger.info("=" * 100)

    logger.info(
        "Run ID               : %s",
        RUN_ID
    )

    logger.info(
        "States               : %s",
        total_states
    )

    logger.info(
        "Districts configured : %s",
        total_districts
    )

    logger.info(
        "Successful districts : %s",
        total_successful
    )

    logger.info(
        "Skipped districts    : %s",
        total_skipped
    )

    logger.info(
        "Failed districts     : %s",
        total_failed
    )

    logger.info(
        "Records extracted    : %s",
        total_records
    )

    logger.info(
        "Total elapsed time   : %s",
        format_elapsed(
            overall_elapsed
        )
    )

    logger.info(
        "Log file             : %s",
        LOG_FILE
    )

    logger.info("=" * 100)


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    main()