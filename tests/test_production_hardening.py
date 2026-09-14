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
