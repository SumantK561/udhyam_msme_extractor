import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import udyam_extractor as extractor
from config import load_settings
from run_udyam import build_run_summary, reconcile_run


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, *args, **kwargs):
        self.messages.append(("INFO", args))

    def warning(self, *args, **kwargs):
        self.messages.append(("WARNING", args))

    def error(self, *args, **kwargs):
        self.messages.append(("ERROR", args))

    def exception(self, *args, **kwargs):
        self.messages.append(("EXCEPTION", args))


def test_run_id_is_unique():
    first = extractor.get_run_id()
    second = extractor.get_run_id()
    assert first != second
    assert "_" in first


def test_sha256(tmp_path):
    path = tmp_path / "batch.csv"
    path.write_bytes(b"abc")
    assert (
        extractor.calculate_file_sha256(path)
        == "ba7816bf8f01cfea414140de5dae2223"
           "b00361a396177a9cb410ff61f20015ad"
    )


def test_configuration_defaults(monkeypatch):
    # Patch load_dotenv so a local .env file cannot bleed into this test.
    monkeypatch.setattr("config.load_dotenv", lambda: None)
    monkeypatch.delenv("UDYAM_MAX_WORKERS", raising=False)
    monkeypatch.delenv("UDYAM_BATCH_SIZE", raising=False)
    monkeypatch.delenv("UDYAM_MAX_RETRIES", raising=False)
    monkeypatch.delenv("UDYAM_TEST_STATE", raising=False)

    settings = load_settings()

    assert settings.max_workers == 3
    assert settings.batch_size == 10000
    assert settings.max_retries == 5
    assert settings.test_state == "ANDAMAN AND NICOBAR ISLANDS"


def test_configuration_validation(monkeypatch):
    monkeypatch.setenv("UDYAM_MAX_WORKERS", "0")
    with pytest.raises(ValueError, match="UDYAM_MAX_WORKERS"):
        load_settings()


def test_short_page_is_retried(monkeypatch):
    logger = FakeLogger()
    responses = [
        {"status": "ok", "count": 9998, "total": 100000, "records": [{}] * 9998},
        {"status": "ok", "count": 10000, "total": 100000, "records": [{}] * 10000},
    ]

    class FakeResult:
        returncode = 0
        stderr = ""
        stdout = "200"

    def fake_run(cmd, **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        response = responses.pop(0)
        output_path.write_text(json.dumps(response), encoding="utf-8")
        return FakeResult()

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)
    monkeypatch.setattr(extractor.random, "uniform", lambda *_: 0)
    monkeypatch.setattr(extractor, "RETRY_BACKOFF_BASE", 0)
    monkeypatch.setattr(extractor, "RETRY_BACKOFF_MAX", 0)
    monkeypatch.setattr(extractor, "RETRY_JITTER", 0)

    result = extractor.fetch_batch("key", "TEST", 0, logger)

    assert len(result["records"]) == 10000
    assert len(responses) == 0


def test_http_429_exhaustion_is_structured(monkeypatch):
    logger = FakeLogger()

    class FakeResult:
        returncode = 0
        stderr = ""
        stdout = "429"

    def fake_run(cmd, **kwargs):
        return FakeResult()

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)
    monkeypatch.setattr(extractor.random, "uniform", lambda *_: 0)
    monkeypatch.setattr(extractor, "RETRY_BACKOFF_BASE", 0)
    monkeypatch.setattr(extractor, "RETRY_BACKOFF_MAX", 0)
    monkeypatch.setattr(extractor, "RETRY_JITTER", 0)
    monkeypatch.setattr(extractor, "RATE_LIMIT_DELAY", 0)

    with pytest.raises(extractor.ExtractionError) as exc:
        extractor.fetch_batch("key", "TEST", 0, logger)

    assert exc.value.reason == "RETRY_EXHAUSTED"
    assert exc.value.stage == "API_FETCH"
    assert exc.value.retry_count == extractor.MAX_RETRIES


def test_shutdown_event_interrupts_retry(monkeypatch):
    logger = FakeLogger()
    extractor.request_shutdown()

    with pytest.raises(extractor.ShutdownRequested):
        extractor.fetch_batch("key", "TEST", 0, logger)

    extractor.reset_shutdown()


def test_failure_metadata_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, "CHECKPOINT_ROOT", tmp_path / "checkpoints")
    logger = FakeLogger()
    cp = {
        "run_id": "RUN1",
        "state": "TEST",
        "total_records": 100,
        "records_written": 20,
        "last_completed_offset": 20,
        "status": "IN_PROGRESS",
    }

    result = extractor.mark_state_failed(
        cp,
        "RUN1",
        "TEST",
        logger,
        reason="RETRY_EXHAUSTED",
        stage="API_FETCH",
        detail="temporary failure",
        retry_count=5,
        http_status=503,
    )

    assert result["status"] == "FAILED"
    assert result["failure_reason"] == "RETRY_EXHAUSTED"
    assert result["failure_stage"] == "API_FETCH"
    assert result["retry_count"] == 5
    assert result["http_status"] == 503
    checkpoint = (
        tmp_path
        / "checkpoints"
        / "RUN1"
        / "TEST.json"
    )
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["failure_reason"] == "RETRY_EXHAUSTED"


def test_reconcile_run():
    logger = FakeLogger()
    results = [
        {"state": "A", "status": "COMPLETED", "total_records": 100, "records_written": 100},
        {"state": "B", "status": "COMPLETED", "total_records": 200, "records_written": 200},
    ]
    assert reconcile_run(results, logger) is True

    results[1]["records_written"] = 199
    assert reconcile_run(results, logger) is False


def test_run_summary_contains_failures():
    summary = build_run_summary(
        run_id="RUN1",
        started_at=SimpleNamespace(isoformat=lambda: "start"),
        completed_at=SimpleNamespace(isoformat=lambda: "end"),
        states=["A"],
        results=[
            {
                "state": "A",
                "status": "FAILED",
                "failure_reason": "RETRY_EXHAUSTED",
                "failure_stage": "API_FETCH",
                "failure_detail": "failed",
                "retry_count": 5,
                "http_status": 503,
                "failed_at": "now",
            }
        ],
        expected_records=100,
        actual_records=0,
        reconciliation_status="FAILED",
        run_status="FAILED",
    )

    assert summary["failures"][0]["failure_reason"] == "RETRY_EXHAUSTED"
    assert summary["run_status"] == "FAILED"


def test_gcs_storage_configuration(monkeypatch):
    monkeypatch.setenv("UDYAM_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("UDYAM_GCS_BUCKET", "prod_us_dataengineering")
    settings = load_settings()
    assert settings.storage_backend == "gcs"
    assert settings.gcs_bucket == "prod_us_dataengineering"


def test_gcs_storage_requires_bucket(monkeypatch):
    monkeypatch.setenv("UDYAM_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("UDYAM_GCS_BUCKET", "")
    with pytest.raises(ValueError, match="UDYAM_GCS_BUCKET"):
        load_settings()


def test_local_storage_validates_checksum(tmp_path):
    from storage import LocalStorage
    path = tmp_path / "batch.csv"
    path.write_bytes(b"abc")
    record = {
        "batch_file": str(path),
        "checksum": extractor.calculate_file_sha256(path),
    }
    valid, reason = LocalStorage().validate_artifact(record, extractor.calculate_file_sha256)
    assert valid is True
    assert reason == ""

    path.write_bytes(b"tampered")
    valid, reason = LocalStorage().validate_artifact(record, extractor.calculate_file_sha256)
    assert valid is False
    assert reason == "ChecksumMismatch"


def test_gcs_object_layout():
    from storage import GCSStorage

    backend = GCSStorage.__new__(GCSStorage)
    backend.bucket_name = "prod_us_dataengineering"
    backend.prefix = "udyam/raw"

    object_name = backend._object_name(
        "RUN1",
        "ANDAMAN AND NICOBAR ISLANDS",
        "RUN1_ANDAMAN AND NICOBAR ISLANDS_0.csv",
        batch=True,
    )

    assert object_name == (
        "udyam/raw/run_id=RUN1/"
        "state=ANDAMAN AND NICOBAR ISLANDS/batches/"
        "RUN1_ANDAMAN AND NICOBAR ISLANDS_0.csv"
    )


def test_s3_storage_requires_bucket(monkeypatch):
    monkeypatch.setenv("UDYAM_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("UDYAM_S3_BUCKET", "")
    with pytest.raises(ValueError, match="UDYAM_S3_BUCKET"):
        load_settings()


def test_s3_object_layout_and_uri():
    from storage import S3Storage

    backend = S3Storage.__new__(S3Storage)
    backend.bucket_name = "prod-us-dataengineering"
    backend.prefix = "udyam/raw"

    object_name = backend._object_name("RUN1", "GOA", "RUN1_GOA_0.csv", batch=True)

    assert object_name == "udyam/raw/run_id=RUN1/state=GOA/batches/RUN1_GOA_0.csv"
    assert backend._uri(object_name) == (
        "s3://prod-us-dataengineering/"
        "udyam/raw/run_id=RUN1/state=GOA/batches/RUN1_GOA_0.csv"
    )


def _fake_object_store(backend_cls, objects):
    """Build a backend whose _head reads from an in-memory object map."""
    backend = backend_cls.__new__(backend_cls)
    backend.bucket_name = "test-bucket"
    backend.prefix = "udyam/raw"
    backend._head = objects.get
    return backend


@pytest.mark.parametrize(
    "backend_name, scheme, label",
    [("GCSStorage", "gs", "GCS"), ("S3Storage", "s3", "S3")],
)
def test_object_storage_validate_artifact(backend_name, scheme, label):
    import storage

    objects = {
        "udyam/raw/run_id=RUN1/state=GOA/batches/batch.csv": (128, "abc123"),
        "udyam/raw/run_id=RUN1/state=GOA/batches/empty.csv": (0, "abc123"),
    }
    backend = _fake_object_store(getattr(storage, backend_name), objects)

    def validate(batch_file, checksum="abc123"):
        return backend.validate_artifact(
            {"batch_file": batch_file, "checksum": checksum},
            extractor.calculate_file_sha256,
        )

    prefix = f"{scheme}://test-bucket/udyam/raw/run_id=RUN1/state=GOA/batches"

    assert validate(f"{prefix}/batch.csv") == (True, "")
    assert validate(f"{prefix}/batch.csv", "wrong") == (False, "ChecksumMismatch")
    assert validate(f"{prefix}/empty.csv") == (False, f"{label}ObjectEmpty")
    assert validate(f"{prefix}/missing.csv") == (False, f"{label}ObjectNotFound")
    assert validate("file:///tmp/batch.csv") == (False, f"Invalid{label}Uri")
    assert validate(f"{scheme}://other-bucket/x.csv") == (
        False,
        f"Unexpected{label}Bucket",
    )
    assert validate("") == (False, "MissingBatchFile")
    assert validate(f"{prefix}/batch.csv", "") == (False, "MissingChecksum")
