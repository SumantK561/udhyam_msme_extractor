from scripts.load_to_snowflake import (
    Settings,
    copy_compacted_file,
    process_compacted_file,
)


def _settings():
    return Settings(
        account="account",
        user="user",
        authenticator="externalbrowser",
        password=None,
        role="loader",
        warehouse="warehouse",
        database="UDYAM",
        schema="RAW",
        stage="S3_STAGE",
        raw_table="MSME",
        ingestion_batch_table="INGESTION_BATCH",
        run_id="RUN1",
    )


def _compact_record():
    batch = {
        "batch_id": "RUN1_GOA_0",
        "offset": 0,
        "record_count": 1000,
        "checksum": "source-checksum",
        "source_file": (
            "udyam/raw/run_id=RUN1/state=GOA/batches/RUN1_GOA_0.csv"
        ),
        "source_uri": (
            "s3://bucket/udyam/raw/run_id=RUN1/state=GOA/"
            "batches/RUN1_GOA_0.csv"
        ),
    }
    return {
        "record_type": "compacted_file",
        "run_id": "RUN1",
        "state": "GOA",
        "batch_file": (
            "s3://bucket/udyam/raw/run_id=RUN1/state=GOA/"
            "batches/COMPACTED_00000.csv"
        ),
        "checksum": "compact-checksum",
        "record_count": 1000,
        "batches": [batch],
    }


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeCursor:
    def __init__(self, *, existing_rows=False, ledger_status=None):
        self.connection = FakeConnection()
        self.existing_rows = existing_rows
        self.ledger_status = ledger_status
        self.copy_executed = False
        self.ledger_merge = None
        self.current_rows = []
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))
        if "SELECT BATCH_ID, LOAD_STATUS" in sql:
            self.current_rows = (
                [
                    (
                        "RUN1_GOA_0",
                        self.ledger_status,
                        1000,
                        0,
                        "source-checksum",
                    )
                ]
                if self.ledger_status
                else []
            )
        elif "SELECT\n                _BATCH_ID" in sql:
            if self.existing_rows or self.copy_executed:
                self.current_rows = [
                    (
                        "RUN1_GOA_0",
                        1000,
                        1,
                        "udyam/raw/run_id=RUN1/state=GOA/batches/RUN1_GOA_0.csv",
                        0,
                        1,
                    )
                ]
            else:
                self.current_rows = []
        elif "INSERT INTO" in sql:
            self.copy_executed = True
            self.current_rows = []
        elif "MERGE INTO" in sql:
            self.ledger_merge = (sql, params)
            self.current_rows = []
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")
        return self

    def fetchall(self):
        return self.current_rows


def test_compacted_insert_maps_embedded_batch_metadata():
    cursor = FakeCursor()
    record = _compact_record()
    copy_compacted_file(cursor, _settings(), record, record["batches"])

    sql, params = cursor.executions[0]
    assert "t.$10" in sql
    assert "t.$11" in sql
    assert "t.$12" in sql
    assert sql.lstrip().startswith("INSERT INTO")
    assert "WHERE t.$10 IN (%s)" in sql
    assert params == ("RUN1_GOA_0",)


def test_zero_files_processed_is_reconciled_from_raw_rows():
    cursor = FakeCursor()
    loaded, skipped = process_compacted_file(
        cursor,
        _settings(),
        _compact_record(),
    )

    assert cursor.copy_executed is True
    assert (loaded, skipped) == (1000, 0)
    assert cursor.connection.commits == 1
    assert cursor.ledger_merge is not None


def test_failed_ledger_with_matching_raw_rows_is_reconciled_without_copy():
    cursor = FakeCursor(existing_rows=True, ledger_status="FAILED")
    loaded, skipped = process_compacted_file(
        cursor,
        _settings(),
        _compact_record(),
    )

    assert cursor.copy_executed is False
    assert (loaded, skipped) == (0, 1000)
    assert cursor.connection.commits == 1
    assert "LOADED" in cursor.ledger_merge[1]
