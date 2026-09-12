# Udyam MSME State-level runner

import os
import time

from dotenv import load_dotenv

from udyam_extractor import (
    extract_state,
    extract_states,
    format_elapsed,
    get_run_id,
    setup_logger,
)


TEST_STATE = "ANDAMAN AND NICOBAR ISLANDS"  # Set to None for all States
MAX_WORKERS = 3


STATES = [
    "ANDAMAN AND NICOBAR ISLANDS",
    "ANDHRA PRADESH",
    "ARUNACHAL PRADESH",
    "ASSAM",
    "BIHAR",
    "CHANDIGARH",
    "CHHATTISGARH",
    "DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
    "DELHI",
    "GOA",
    "GUJARAT",
    "HARYANA",
    "HIMACHAL PRADESH",
    "JAMMU AND KASHMIR",
    "JHARKHAND",
    "KARNATAKA",
    "KERALA",
    "LADAKH",
    "LAKSHADWEEP",
    "MADHYA PRADESH",
    "MAHARASHTRA",
    "MANIPUR",
    "MEGHALAYA",
    "MIZORAM",
    "NAGALAND",
    "ODISHA",
    "PUDUCHERRY",
    "PUNJAB",
    "RAJASTHAN",
    "SIKKIM",
    "TAMIL NADU",
    "TELANGANA",
    "TRIPURA",
    "UTTAR PRADESH",
    "UTTARAKHAND",
    "WEST BENGAL",
]


def reconcile_run(results, logger) -> bool:
    """
    Validate the integrity of the complete extraction run.

    Run-level reconciliation passes only when:

    1. Every requested state completed successfully.
    2. Every state has an API total.
    3. Aggregate API totals exactly match aggregate persisted records.

    Returns True when run-level reconciliation passes,
    otherwise returns False.
    """

    if not results:
        logger.error(
            "RUN RECONCILIATION FAILED | "
            "Reason=NoStateResults"
        )
        return False

    failed_states = [
        r.get("state", "UNKNOWN")
        for r in results
        if r.get("status") != "COMPLETED"
    ]

    if failed_states:
        logger.error(
            "RUN RECONCILIATION FAILED | "
            "Reason=StateFailure | "
            "States=%s",
            ", ".join(failed_states),
        )
        return False

    missing_totals = [
        r.get("state", "UNKNOWN")
        for r in results
        if r.get("total_records") is None
    ]

    if missing_totals:
        logger.error(
            "RUN RECONCILIATION FAILED | "
            "Reason=MissingAPITotal | "
            "States=%s",
            ", ".join(missing_totals),
        )
        return False

    expected = sum(
        int(r.get("total_records") or 0)
        for r in results
    )

    actual = sum(
        int(r.get("records_written") or 0)
        for r in results
    )

    if expected != actual:
        logger.error(
            "RUN RECONCILIATION FAILED | "
            "Reason=RecordCountMismatch | "
            "ExpectedRecords=%s | "
            "ActualRecords=%s | "
            "Difference=%s",
            expected,
            actual,
            actual - expected,
        )
        return False

    logger.info(
        "RUN RECONCILIATION PASSED | "
        "States=%s | "
        "ExpectedRecords=%s | "
        "ActualRecords=%s",
        len(results),
        expected,
        actual,
    )

    return True


def main() -> bool:
    load_dotenv()

    logger = setup_logger()
    started = time.perf_counter()

    configured_run_id = os.getenv("UDYAM_RUN_ID")
    run_id = get_run_id(configured_run_id)

    api_key = os.getenv("UDYAM_API_KEY")

    if not api_key:
        logger.error(
            "UDYAM_API_KEY is not configured. Add it to .env"
        )
        return False

    states = [TEST_STATE] if TEST_STATE else STATES

    invalid = [
        state
        for state in states
        if state not in STATES
    ]

    if invalid:
        logger.error(
            "Invalid State(s): %s",
            ", ".join(invalid),
        )
        return False

    logger.info("=" * 80)
    logger.info(
        "UDYAM MSME STATE EXTRACTION STARTED"
    )

    logger.info(
        "Run ID=%s | States=%s | MaxWorkers=%s | "
        "BatchSize=10000 | TestState=%s | ResumeMode=%s",
        run_id,
        len(states),
        MAX_WORKERS,
        TEST_STATE or "ALL",
        "EXISTING" if configured_run_id else "NEW",
    )

    logger.info("=" * 80)

    if len(states) == 1:
        results = [
            extract_state(
                api_key,
                states[0],
                run_id,
                logger,
            )
        ]
    else:
        results = extract_states(
            api_key,
            states,
            run_id,
            logger,
            MAX_WORKERS,
        )

    elapsed = time.perf_counter() - started

    completed = sum(
        r.get("status") == "COMPLETED"
        for r in results
    )

    failed = sum(
        r.get("status") == "FAILED"
        for r in results
    )

    records = sum(
        int(r.get("records_written") or 0)
        for r in results
    )

    logger.info("=" * 80)
    logger.info("FINAL EXECUTION SUMMARY")

    logger.info(
        "Run ID=%s | States Requested=%s | "
        "Completed=%s | Failed=%s | Records=%s | Elapsed=%s",
        run_id,
        len(states),
        completed,
        failed,
        records,
        format_elapsed(elapsed),
    )

    logger.info(
        "Log file=%s",
        logger.log_file,
    )

    logger.info("=" * 80)

    # -----------------------------------------------------------------------
    # Run-level reconciliation
    # -----------------------------------------------------------------------

    run_reconciled = reconcile_run(
        results,
        logger,
    )

    if failed:
        logger.error(
            "RUN FAILED | "
            "Reason=StateFailure | "
            "FailedStates=%s",
            failed,
        )

        logger.warning(
            "Execution completed with %s failed State(s). "
            "Re-run to retry/resume.",
            failed,
        )

        return False

    if not run_reconciled:
        logger.error(
            "RUN FAILED | "
            "Reason=RunReconciliationFailure"
        )

        return False

    logger.info(
        "RUN COMPLETED | "
        "RunID=%s | "
        "States=%s | "
        "Records=%s",
        run_id,
        len(states),
        records,
    )

    logger.info(
        "Execution completed successfully."
    )

    return True


if __name__ == "__main__":
    success = main()
    raise SystemExit(0 if success else 1)
