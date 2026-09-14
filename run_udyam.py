"""Production entry point for the Udyam MSME extractor."""

import os
import signal
import time

from datetime import datetime, timezone

from config import load_settings
from udyam_extractor import (
    extract_state,
    extract_states,
    format_elapsed,
    get_run_id,
    get_run_summary_path,
    request_shutdown,
    reset_shutdown,
    setup_logger,
    write_run_summary,
)


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
    """Validate the integrity of the complete extraction run."""
    if not results:
        logger.error(
            "RUN RECONCILIATION FAILED | Reason=NoStateResults"
        )
        return False

    failed_states = [
        r.get("state", "UNKNOWN")
        for r in results
        if r.get("status") != "COMPLETED"
    ]

    if failed_states:
        logger.error(
            "RUN RECONCILIATION FAILED | Reason=StateFailure | States=%s",
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
            "RUN RECONCILIATION FAILED | Reason=MissingAPITotal | States=%s",
            ", ".join(missing_totals),
        )
        return False

    expected = sum(int(r.get("total_records") or 0) for r in results)
    actual = sum(int(r.get("records_written") or 0) for r in results)

    if expected != actual:
        logger.error(
            "RUN RECONCILIATION FAILED | Reason=RecordCountMismatch | "
            "ExpectedRecords=%s | ActualRecords=%s | Difference=%s",
            expected,
            actual,
            actual - expected,
        )
        return False

    logger.info(
        "RUN RECONCILIATION PASSED | States=%s | "
        "ExpectedRecords=%s | ActualRecords=%s",
        len(results),
        expected,
        actual,
    )
    return True


def build_run_summary(
    run_id,
    started_at,
    completed_at,
    states,
    results,
    expected_records,
    actual_records,
    reconciliation_status,
    run_status,
):
    """Build the durable run-level summary including structured failures."""
    completed_states = sum(
        r.get("status") == "COMPLETED" for r in results
    )
    failed_states = sum(
        r.get("status") == "FAILED" for r in results
    )

    failures = [
        {
            key: r.get(key)
            for key in (
                "state",
                "failure_reason",
                "failure_stage",
                "failure_detail",
                "retry_count",
                "http_status",
                "failed_at",
            )
            if r.get(key) is not None
        }
        for r in results
        if r.get("status") == "FAILED"
    ]

    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "requested_states": len(states),
        "completed_states": completed_states,
        "failed_states": failed_states,
        "expected_records": expected_records,
        "actual_records": actual_records,
        "reconciliation_status": reconciliation_status,
        "run_status": run_status,
        "failures": failures,
    }


def install_signal_handlers(logger):
    """Install cooperative SIGINT/SIGTERM handlers for Windows and Linux."""
    def handle_shutdown(signum, _frame):
        signal_name = signal.Signals(signum).name
        logger.warning(
            "SHUTDOWN REQUESTED | Signal=%s | "
            "Current API request will finish before workers stop",
            signal_name,
        )
        request_shutdown()

    signal.signal(signal.SIGINT, handle_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_shutdown)


def main() -> bool:
    reset_shutdown()
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"CONFIGURATION ERROR: {exc}")
        return False

    logger = setup_logger(settings.log_level)
    install_signal_handlers(logger)

    configured_run_id = os.getenv("UDYAM_RUN_ID")
    run_id = get_run_id(configured_run_id)

    if not settings.api_key:
        logger.error(
            "UDYAM_API_KEY is not configured. Add it to .env"
        )
        return False

    states = [settings.test_state] if settings.test_state else STATES

    invalid = [state for state in states if state not in STATES]
    if invalid:
        logger.error("Invalid State(s): %s", ", ".join(invalid))
        return False

    logger.info("=" * 80)
    logger.info("UDYAM MSME STATE EXTRACTION STARTED")
    logger.info(
        "Run ID=%s | States=%s | MaxWorkers=%s | BatchSize=%s | "
        "TestState=%s | ResumeMode=%s",
        run_id,
        len(states),
        settings.max_workers,
        settings.batch_size,
        settings.test_state or "ALL",
        "EXISTING" if configured_run_id else "NEW",
    )
    logger.info("=" * 80)

    if len(states) == 1:
        results = [
            extract_state(
                settings.api_key,
                states[0],
                run_id,
                logger,
            )
        ]
    else:
        results = extract_states(
            settings.api_key,
            states,
            run_id,
            logger,
            settings.max_workers,
        )

    elapsed = time.perf_counter() - started
    completed = sum(r.get("status") == "COMPLETED" for r in results)
    failed = sum(r.get("status") == "FAILED" for r in results)
    records = sum(int(r.get("records_written") or 0) for r in results)

    logger.info("=" * 80)
    logger.info("FINAL EXECUTION SUMMARY")
    logger.info(
        "Run ID=%s | States Requested=%s | Completed=%s | "
        "Failed=%s | Records=%s | Elapsed=%s",
        run_id,
        len(states),
        completed,
        failed,
        records,
        format_elapsed(elapsed),
    )
    logger.info("Log file=%s", logger.log_file)
    logger.info("=" * 80)

    run_reconciled = reconcile_run(results, logger)
    expected_records = sum(
        int(r.get("total_records") or 0) for r in results
    )
    completed_at = datetime.now(timezone.utc)

    run_status = "COMPLETED" if run_reconciled and not failed else "FAILED"
    reconciliation_status = "PASSED" if run_reconciled else "FAILED"

    if run_status == "FAILED":
        logger.error(
            "RUN FAILED | Reason=%s",
            "StateFailure" if failed else "RunReconciliationFailure",
        )
    else:
        logger.info("RUN COMPLETED")

    summary = build_run_summary(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        states=states,
        results=results,
        expected_records=expected_records,
        actual_records=records,
        reconciliation_status=reconciliation_status,
        run_status=run_status,
    )

    try:
        write_run_summary(run_id=run_id, summary=summary)
        logger.info(
            "RUN SUMMARY WRITTEN | Path=%s",
            get_run_summary_path(run_id),
        )
    except OSError as exc:
        logger.exception(
            "RUN SUMMARY WRITE FAILED | Error=%s",
            exc,
        )
        return False

    if run_status == "FAILED":
        logger.warning(
            "Execution failed. Re-run with UDYAM_RUN_ID=%s to retry/resume.",
            run_id,
        )
        return False

    return True


if __name__ == "__main__":
    success = main()
    raise SystemExit(0 if success else 1)
