"""
Idempotent GCS -> Snowflake RAW loader for Udyam MSME.

Flow:
    GCS manifest
        -> SUCCESS batches
        -> INGESTION_BATCH idempotency check
        -> COPY INTO RAW
        -> row-count reconciliation
        -> INGESTION_BATCH update

Development authentication:
    Snowflake External Browser / SSO

Production authentication:
    Use a non-interactive Snowflake authentication mechanism.
    Never hard-code credentials or secrets in this application.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

import snowflake.connector
from dotenv import load_dotenv


LOGGER = logging.getLogger("udyam.snowflake_loader")


class LoaderError(RuntimeError):
    """Raised when the Snowflake loader cannot safely continue."""


@dataclass(frozen=True)
class Settings:
    account: str
    user: str
    authenticator: str
    role: str
    warehouse: str
    database: str
    schema: str
    stage: str
    raw_table: str
    ingestion_batch_table: str
    run_id: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv()

        required = {
            "SNOWFLAKE_ACCOUNT": os.getenv("SNOWFLAKE_ACCOUNT"),
            "SNOWFLAKE_USER": os.getenv("SNOWFLAKE_USER"),
            "SNOWFLAKE_AUTHENTICATOR": os.getenv(
                "SNOWFLAKE_AUTHENTICATOR",
                "externalbrowser",
            ),
            "SNOWFLAKE_ROLE": os.getenv("SNOWFLAKE_ROLE"),
            "SNOWFLAKE_WAREHOUSE": os.getenv("SNOWFLAKE_WAREHOUSE"),
            "SNOWFLAKE_DATABASE": os.getenv("SNOWFLAKE_DATABASE"),
            "SNOWFLAKE_SCHEMA": os.getenv("SNOWFLAKE_SCHEMA"),
            "SNOWFLAKE_STAGE": os.getenv("SNOWFLAKE_STAGE"),
        }

        missing = [
            name
            for name, value in required.items()
            if not value
        ]

        if missing:
            raise LoaderError(
                "Missing required Snowflake configuration: "
                + ", ".join(missing)
            )

        return cls(
            account=required["SNOWFLAKE_ACCOUNT"],
            user=required["SNOWFLAKE_USER"],
            authenticator=required["SNOWFLAKE_AUTHENTICATOR"],
            role=required["SNOWFLAKE_ROLE"],
            warehouse=required["SNOWFLAKE_WAREHOUSE"],
            database=required["SNOWFLAKE_DATABASE"],
            schema=required["SNOWFLAKE_SCHEMA"],
            stage=required["SNOWFLAKE_STAGE"],
            raw_table=os.getenv(
                "SNOWFLAKE_RAW_TABLE",
                "MSME",
            ),
            ingestion_batch_table=os.getenv(
                "SNOWFLAKE_INGESTION_BATCH_TABLE",
                "INGESTION_BATCH",
            ),
            run_id=os.getenv("UDYAM_RUN_ID"),
        )


def quote_identifier(identifier: str) -> str:
    """
    Safely quote a Snowflake identifier.

    Identifiers come from configuration, not from the source data.
    """

    if not identifier:
        raise LoaderError("Identifier cannot be empty.")

    if "\x00" in identifier:
        raise LoaderError(
            "Invalid null character in identifier."
        )

    return '"' + identifier.replace('"', '""') + '"'


def qualified_name(
    database: str,
    schema: str,
    object_name: str,
) -> str:
    """Build a safely quoted three-part Snowflake object name."""

    return ".".join(
        [
            quote_identifier(database),
            quote_identifier(schema),
            quote_identifier(object_name),
        ]
    )


def sql_string(value: str) -> str:
    """Return a safely escaped Snowflake SQL string literal."""

    return "'" + value.replace("'", "''") + "'"


def create_connection(settings: Settings):
    """Create a Snowflake connection using configured authentication."""

    LOGGER.info(
        "Connecting to Snowflake account=%s role=%s warehouse=%s "
        "database=%s schema=%s",
        settings.account,
        settings.role,
        settings.warehouse,
        settings.database,
        settings.schema,
    )

    return snowflake.connector.connect(
        account=settings.account,
        user=settings.user,
        authenticator=settings.authenticator,
        role=settings.role,
        warehouse=settings.warehouse,
        database=settings.database,
        schema=settings.schema,
    )


def load_manifest(
    cursor,
    settings: Settings,
) -> list[dict[str, Any]]:
    """
    Read the manifest.jsonl for exactly one configured Udyam run.

    The external stage is already configured to point to:

        gs://prod_us_dataengineering/udyam/raw/
    """

    if not settings.run_id:
        raise LoaderError(
            "UDYAM_RUN_ID must be set. "
            "The loader requires an explicit run ID to prevent "
            "accidental cross-run ingestion."
        )

    pattern = (
        rf".*run_id={re.escape(settings.run_id)}/manifest\.jsonl$"
    )

    stage_name = quote_identifier(settings.stage)

    sql = f"""
        SELECT $1
        FROM @{stage_name}
        (
            FILE_FORMAT => 'UDYAM_JSON_FORMAT',
            PATTERN => {sql_string(pattern)}
        )
    """

    LOGGER.info(
        "Reading manifest from stage=%s run_id=%s",
        settings.stage,
        settings.run_id,
    )

    cursor.execute(sql)

    records: list[dict[str, Any]] = []

    for row in cursor.fetchall():
        value = row[0]

        if isinstance(value, str):
            value = json.loads(value)

        if not isinstance(value, dict):
            raise LoaderError(
                "Unexpected manifest record type: "
                f"{type(value).__name__}"
            )

        records.append(value)

    if not records:
        raise LoaderError(
            "No manifest records found for the requested run."
        )

    return records


def get_batch_status(
    cursor,
    settings: Settings,
    batch_id: str,
) -> tuple[
    str | None,
    int | None,
    int | None,
    str | None,
]:
    """
    Read the current ingestion ledger state for a batch.

    Returns:
        load_status,
        expected_rows,
        loaded_rows,
        checksum
    """

    table = qualified_name(
        settings.database,
        settings.schema,
        settings.ingestion_batch_table,
    )

    sql = f"""
        SELECT
            LOAD_STATUS,
            EXPECTED_ROWS,
            LOADED_ROWS,
            CHECKSUM
        FROM {table}
        WHERE BATCH_ID = %s
    """

    cursor.execute(sql, (batch_id,))
    row = cursor.fetchone()

    if row is None:
        return None, None, None, None

    return row[0], row[1], row[2], row[3]


def should_skip(
    status: str | None,
    expected_rows: int,
    loaded_rows: int | None,
    ledger_expected_rows: int | None,
    manifest_checksum: str,
    ledger_checksum: str | None,
) -> bool:
    """
    Determine whether a batch can safely be skipped.

    A batch is skipped only when:
        - ledger status is LOADED
        - ledger expected rows match manifest expected rows
        - ledger loaded rows match manifest expected rows
        - ledger checksum matches manifest checksum

    This prevents a row-count-only match from being treated as
    proof of successful ingestion.
    """

    return (
        status == "LOADED"
        and ledger_expected_rows is not None
        and int(ledger_expected_rows) == int(expected_rows)
        and loaded_rows is not None
        and int(loaded_rows) == int(expected_rows)
        and ledger_checksum is not None
        and ledger_checksum == manifest_checksum
    )


def copy_batch(
    cursor,
    settings: Settings,
    manifest_record: dict[str, Any],
) -> int:
    """
    Load exactly one manifest batch file into the Snowflake RAW table.

    No business transformations are performed here.
    """

    batch_id = str(manifest_record["batch_id"])
    state = str(manifest_record["state"])
    run_id = str(manifest_record["run_id"])
    expected_rows = int(manifest_record["record_count"])
    source_offset = int(manifest_record["offset"])

    batch_file = str(manifest_record["batch_file"])

    # The manifest must contain a GCS URI.
    if not batch_file.startswith("gs://"):
        raise LoaderError(
            f"Unsupported batch_file URI: {batch_file}"
        )

    # The configured external stage points to:
    #
    # gs://prod_us_dataengineering/udyam/raw/
    #
    # Convert the full GCS URI into a stage-relative object path.
    marker = "/udyam/raw/"

    if marker not in batch_file:
        raise LoaderError(
            "Batch file is outside the expected Udyam RAW prefix: "
            f"{batch_file}"
        )

    relative_path = batch_file.split(marker, 1)[1]

    if not relative_path:
        raise LoaderError(
            "Could not derive stage-relative path from: "
            f"{batch_file}"
        )

    # COPY is deliberately restricted to exactly this one file.
    pattern = rf".*{re.escape(relative_path)}$"

    raw_table = qualified_name(
        settings.database,
        settings.schema,
        settings.raw_table,
    )

    stage_name = quote_identifier(settings.stage)

    sql = f"""
        COPY INTO {raw_table}
        (
            LG_ST_CODE,
            STATE,
            LG_DT_CODE,
            DISTRICT,
            PINCODE,
            REGISTRATION_DATE,
            ENTERPRISE_NAME,
            COMMUNICATION_ADDRESS,
            ACTIVITIES,
            _RUN_ID,
            _STATE,
            _BATCH_ID,
            _SOURCE_FILE,
            _SOURCE_OFFSET,
            _INGESTED_AT
        )
        FROM (
            SELECT
                t.$1,
                t.$2,
                t.$3,
                t.$4,
                t.$5,
                t.$6,
                t.$7,
                t.$8,
                t.$9,
                {sql_string(run_id)},
                {sql_string(state)},
                {sql_string(batch_id)},
                METADATA$FILENAME,
                {source_offset},
                CURRENT_TIMESTAMP()
            FROM @{stage_name}
            (
                FILE_FORMAT => 'UDYAM_CSV_FORMAT',
                PATTERN => {sql_string(pattern)}
            ) t
        )
    """

    LOGGER.info(
        "COPY batch_id=%s expected_rows=%d",
        batch_id,
        expected_rows,
    )

    cursor.execute(sql)
    results = cursor.fetchall()

    if not results:
        raise LoaderError(
            f"Snowflake COPY returned no result for batch {batch_id}"
        )

    total_loaded = 0

    for result in results:
        # COPY result columns:
        #
        # 0 = file
        # 1 = status
        # 2 = rows_parsed
        # 3 = rows_loaded
        #
        if len(result) < 4:
            raise LoaderError(
                f"Unexpected Snowflake COPY result for batch "
                f"{batch_id}: {result}"
            )

        file_name = result[0]
        copy_status = result[1]
        rows_parsed = result[2]
        rows_loaded = result[3]

        LOGGER.info(
            "COPY result batch_id=%s file=%s status=%s "
            "rows_parsed=%s rows_loaded=%s",
            batch_id,
            file_name,
            copy_status,
            rows_parsed,
            rows_loaded,
        )

        if rows_loaded is not None:
            total_loaded += int(rows_loaded)

    if total_loaded != expected_rows:
        raise LoaderError(
            f"Row reconciliation failed for batch {batch_id}: "
            f"expected={expected_rows}, "
            f"loaded={total_loaded}"
        )

    return total_loaded


def update_batch_ledger(
    cursor,
    settings: Settings,
    manifest_record: dict[str, Any],
    loaded_rows: int,
    status: str = "LOADED",
    error_message: str | None = None,
) -> None:
    """
    Insert or update the ingestion ledger for one batch.
    """

    table = qualified_name(
        settings.database,
        settings.schema,
        settings.ingestion_batch_table,
    )

    sql = f"""
        MERGE INTO {table} target
        USING (
            SELECT
                %s AS RUN_ID,
                %s AS BATCH_ID,
                %s AS STATE,
                %s AS SOURCE_FILE,
                %s AS SOURCE_OFFSET,
                %s AS EXPECTED_ROWS,
                %s AS LOADED_ROWS,
                %s AS CHECKSUM,
                %s AS LOAD_STATUS,
                CURRENT_TIMESTAMP() AS LOADED_AT,
                %s AS ERROR_MESSAGE
        ) source
        ON target.BATCH_ID = source.BATCH_ID

        WHEN MATCHED THEN UPDATE SET
            RUN_ID = source.RUN_ID,
            STATE = source.STATE,
            SOURCE_FILE = source.SOURCE_FILE,
            SOURCE_OFFSET = source.SOURCE_OFFSET,
            EXPECTED_ROWS = source.EXPECTED_ROWS,
            LOADED_ROWS = source.LOADED_ROWS,
            CHECKSUM = source.CHECKSUM,
            LOAD_STATUS = source.LOAD_STATUS,
            LOADED_AT = source.LOADED_AT,
            ERROR_MESSAGE = source.ERROR_MESSAGE

        WHEN NOT MATCHED THEN INSERT (
            RUN_ID,
            BATCH_ID,
            STATE,
            SOURCE_FILE,
            SOURCE_OFFSET,
            EXPECTED_ROWS,
            LOADED_ROWS,
            CHECKSUM,
            LOAD_STATUS,
            LOADED_AT,
            ERROR_MESSAGE
        )
        VALUES (
            source.RUN_ID,
            source.BATCH_ID,
            source.STATE,
            source.SOURCE_FILE,
            source.SOURCE_OFFSET,
            source.EXPECTED_ROWS,
            source.LOADED_ROWS,
            source.CHECKSUM,
            source.LOAD_STATUS,
            source.LOADED_AT,
            source.ERROR_MESSAGE
        )
    """

    values = (
        str(manifest_record["run_id"]),
        str(manifest_record["batch_id"]),
        str(manifest_record["state"]),
        str(manifest_record["batch_file"]),
        int(manifest_record["offset"]),
        int(manifest_record["record_count"]),
        int(loaded_rows),
        str(manifest_record["checksum"]),
        status,
        error_message,
    )

    cursor.execute(sql, values)


def process_run(
    cursor,
    settings: Settings,
) -> int:
    """
    Process all SUCCESS batches belonging to the configured run.
    """

    manifest = load_manifest(
        cursor,
        settings,
    )

    success_batches = [
        record
        for record in manifest
        if str(record.get("status", "")).upper() == "SUCCESS"
    ]

    if not success_batches:
        raise LoaderError(
            "Manifest contains no SUCCESS batches."
        )

    # Deterministic processing order.
    success_batches.sort(
        key=lambda record: (
            str(record.get("state", "")),
            int(record.get("offset", 0)),
        )
    )

    loaded_total = 0
    skipped_total = 0

    for record in success_batches:

        required_fields = (
            "run_id",
            "batch_id",
            "state",
            "batch_file",
            "offset",
            "record_count",
            "checksum",
        )

        missing = [
            field
            for field in required_fields
            if field not in record
        ]

        if missing:
            raise LoaderError(
                f"Manifest batch is missing fields: {missing}"
            )

        batch_id = str(record["batch_id"])
        expected_rows = int(record["record_count"])
        manifest_run_id = str(record["run_id"])
        manifest_checksum = str(record["checksum"])

        # Defense-in-depth validation.
        if manifest_run_id != settings.run_id:
            raise LoaderError(
                f"Manifest run_id mismatch for batch {batch_id}: "
                f"expected={settings.run_id}, "
                f"actual={manifest_run_id}"
            )

        if expected_rows < 0:
            raise LoaderError(
                f"Invalid record_count for batch {batch_id}: "
                f"{expected_rows}"
            )

        if not manifest_checksum:
            raise LoaderError(
                f"Missing checksum for batch {batch_id}"
            )

        (
            status,
            ledger_expected,
            ledger_loaded,
            ledger_checksum,
        ) = get_batch_status(
            cursor,
            settings,
            batch_id,
        )

        if status is not None:
            LOGGER.info(
                "Ledger batch_id=%s status=%s expected=%s "
                "loaded=%s checksum_match=%s",
                batch_id,
                status,
                ledger_expected,
                ledger_loaded,
                ledger_checksum == manifest_checksum,
            )

        # Safe idempotent path.
        if should_skip(
            status,
            expected_rows,
            ledger_loaded,
            ledger_expected,
            manifest_checksum,
            ledger_checksum,
        ):
            LOGGER.info(
                "SKIP batch_id=%s expected_rows=%d "
                "loaded_rows=%d",
                batch_id,
                expected_rows,
                ledger_loaded,
            )

            skipped_total += expected_rows
            continue

        # Fail closed when a LOADED record does not match.
        #
        # Automatically loading here could create duplicates.
        if status == "LOADED":
            raise LoaderError(
                "Existing LOADED ledger record does not match "
                f"manifest for batch {batch_id}: "
                f"manifest_expected={expected_rows}, "
                f"ledger_expected={ledger_expected}, "
                f"ledger_loaded={ledger_loaded}, "
                f"manifest_checksum={manifest_checksum}, "
                f"ledger_checksum={ledger_checksum}"
            )

        # Never automatically retry an ambiguous LOADING state.
        #
        # A previous process could have successfully executed COPY
        # but failed before updating the ledger.
        if status == "LOADING":
            raise LoaderError(
                f"Batch {batch_id} is already marked LOADING. "
                "Refusing to automatically retry because a previous "
                "loader may have partially processed this batch. "
                "Investigate the batch before retrying."
            )

        # Perform the actual load.
        try:
            loaded_rows = copy_batch(
                cursor,
                settings,
                record,
            )

            # Only mark LOADED after COPY and reconciliation succeed.
            update_batch_ledger(
                cursor,
                settings,
                record,
                loaded_rows,
                status="LOADED",
            )

            # COPY + ledger update are committed together.
            cursor.connection.commit()

        except Exception as exc:
            # Make sure an unsuccessful transaction cannot remain open.
            cursor.connection.rollback()

            LOGGER.exception(
                "Load failed for batch_id=%s",
                batch_id,
            )

            # Record the failure in a separate transaction.
            try:
                update_batch_ledger(
                    cursor,
                    settings,
                    record,
                    loaded_rows=0,
                    status="FAILED",
                    error_message=str(exc)[:5000],
                )

                cursor.connection.commit()

            except Exception:
                cursor.connection.rollback()

                LOGGER.exception(
                    "Failed to record FAILED state for batch_id=%s",
                    batch_id,
                )

            raise

        loaded_total += loaded_rows

        LOGGER.info(
            "LOADED batch_id=%s rows=%d",
            batch_id,
            loaded_rows,
        )

    LOGGER.info(
        "Run processing complete: loaded_rows=%d "
        "skipped_rows=%d",
        loaded_total,
        skipped_total,
    )

    return loaded_total


def main() -> int:
    """Application entry point."""

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
    )

    conn = None

    try:
        settings = Settings.from_environment()

        LOGGER.info(
            "Starting GCS -> Snowflake loader run_id=%s",
            settings.run_id,
        )

        conn = create_connection(settings)

        cursor = conn.cursor()

        try:
            process_run(
                cursor,
                settings,
            )

            conn.commit()

        finally:
            cursor.close()

        LOGGER.info(
            "Loader completed successfully."
        )

        return 0

    except KeyboardInterrupt:
        LOGGER.error(
            "Loader interrupted."
        )

        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                LOGGER.exception(
                    "Failed to rollback after interruption."
                )

        return 130

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
                LOGGER.info(
                    "Snowflake transaction rolled back."
                )
            except Exception:
                LOGGER.exception(
                    "Failed to rollback Snowflake transaction."
                )

        LOGGER.exception(
            "Loader failed: %s",
            exc,
        )

        return 1

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                LOGGER.exception(
                    "Failed to close Snowflake connection."
                )


if __name__ == "__main__":
    sys.exit(main())