"""Combine small extracted CSV batches into bounded files before loading."""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

# Direct script execution puts scripts/ rather than the repository root on
# sys.path. Add the root so shared top-level modules resolve on Airflow hosts.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from udyam_extractor import (
    CSV_HEADERS,
    OUTPUT_ROOT,
    SETTINGS,
    STORAGE,
    calculate_file_sha256,
)


LOGGER = logging.getLogger("udyam.compactor")
COMPACT_HEADERS = CSV_HEADERS + [
    "__BATCH_ID",
    "__SOURCE_FILE",
    "__SOURCE_OFFSET",
]


class CompactionError(RuntimeError):
    """Raised when extraction batches cannot be safely compacted."""


def _manifest_path(run_id: str) -> Path:
    return OUTPUT_ROOT / run_id / "manifest.jsonl"


def _compaction_manifest_path(run_id: str) -> Path:
    return OUTPUT_ROOT / run_id / "compaction_manifest.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise CompactionError(f"Extraction manifest not found: {path}")

    records = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CompactionError(
                    f"Invalid JSON in {path} at line {line_number}"
                ) from exc
            if not isinstance(record, dict):
                raise CompactionError(
                    f"Unexpected manifest record at {path}:{line_number}"
                )
            records.append(record)
    return records


def _successful_batches(run_id: str) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for record in _read_jsonl(_manifest_path(run_id)):
        if str(record.get("status", "")).upper() != "SUCCESS":
            continue
        batch_id = str(record.get("batch_id", ""))
        if not batch_id or str(record.get("run_id")) != run_id:
            raise CompactionError("Invalid batch identity in extraction manifest")
        previous = by_id.get(batch_id)
        if previous is not None and (
            previous.get("checksum") != record.get("checksum")
            or previous.get("batch_file") != record.get("batch_file")
        ):
            raise CompactionError(
                f"Conflicting manifest entries for batch {batch_id}"
            )
        by_id[batch_id] = record
    if not by_id:
        raise CompactionError(f"No successful extraction batches for {run_id}")
    return sorted(
        by_id.values(),
        key=lambda item: (str(item["state"]), int(item["offset"])),
    )


def _stage_source_file(batch_file: str) -> str:
    parsed = urlparse(batch_file)
    if parsed.scheme not in {"s3", "gs"}:
        raise CompactionError(
            "Snowflake loading requires cloud batch URIs; "
            f"unsupported batch file: {batch_file}"
        )
    if not parsed.path.strip("/"):
        raise CompactionError(f"Missing object path in {batch_file}")
    source_file = unquote(parsed.path.lstrip("/"))
    if not source_file.startswith("udyam/raw/"):
        raise CompactionError(
            "Batch file is outside the Snowflake stage prefix "
            f"udyam/raw/: {batch_file}"
        )
    return source_file


def _existing_compaction_is_valid(
    run_id: str,
    source_batches: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    path = _compaction_manifest_path(run_id)
    if not path.is_file():
        return None
    records = _read_jsonl(path)
    if not records:
        return None
    expected_ids = {str(batch["batch_id"]) for batch in source_batches}
    compacted_batches = [
        batch
        for record in records
        for batch in record.get("batches", [])
    ]
    compacted_ids = {str(batch.get("batch_id")) for batch in compacted_batches}
    if (
        len(compacted_batches) != len(expected_ids)
        or compacted_ids != expected_ids
    ):
        return None
    source_by_id = {str(batch["batch_id"]): batch for batch in source_batches}
    for batch in compacted_batches:
        source = source_by_id[str(batch["batch_id"])]
        if (
            int(batch.get("offset", -1)) != int(source["offset"])
            or int(batch.get("record_count", -1)) != int(source["record_count"])
            or batch.get("checksum") != source["checksum"]
            or batch.get("source_uri") != source["batch_file"]
        ):
            return None
    for record in records:
        if (
            record.get("run_id") != run_id
            or not record.get("batch_file")
            or not record.get("checksum")
            or not isinstance(record.get("batches"), list)
            or int(record.get("record_count", -1))
            != sum(int(batch.get("record_count", 0)) for batch in record["batches"])
        ):
            return None
        valid, _ = STORAGE.validate_artifact(
            record,
            calculate_file_sha256,
        )
        if not valid:
            return None
    return records


def _write_compaction_manifest(
    run_id: str,
    records: list[dict[str, Any]],
) -> Path:
    path = _compaction_manifest_path(run_id)
    temp_path = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as target:
            for record in records:
                target.write(json.dumps(record, ensure_ascii=False) + "\n")
            target.flush()
            os.fsync(target.fileno())
        temp_path.replace(path)
        STORAGE.sync_compaction_manifest(run_id, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return path


def compact_run(run_id: str) -> list[dict[str, Any]]:
    """Create verified, bounded compact files and publish their manifest."""
    source_batches = _successful_batches(run_id)
    existing = _existing_compaction_is_valid(run_id, source_batches)
    if existing is not None:
        STORAGE.sync_compaction_manifest(run_id, _compaction_manifest_path(run_id))
        LOGGER.info(
            "Compaction already complete: run_id=%s files=%d",
            run_id,
            len(existing),
        )
        return existing

    max_rows = SETTINGS.compaction_max_rows
    compact_records: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(
        prefix=f"udyam_compact_{run_id}_",
        dir=str(OUTPUT_ROOT / run_id),
    ) as staging:
        staging_dir = Path(staging)
        chunk_index_by_state: dict[str, int] = {}
        current_state: str | None = None
        current_file = None
        current_writer = None
        current_path: Path | None = None
        current_rows = 0
        current_batches: list[dict[str, Any]] = []

        def publish_chunk() -> None:
            nonlocal current_file, current_writer, current_path
            nonlocal current_rows, current_batches, current_state
            if current_file is None or current_path is None or not current_state:
                return
            current_file.flush()
            os.fsync(current_file.fileno())
            current_file.close()
            current_file = None
            checksum = calculate_file_sha256(current_path)
            index = chunk_index_by_state[current_state]
            batch_file = STORAGE.publish_compacted_batch(
                current_path,
                run_id,
                current_state,
                index,
                checksum,
            )
            compact_records.append(
                {
                    "record_type": "compacted_file",
                    "run_id": run_id,
                    "state": current_state,
                    "batch_file": batch_file,
                    "checksum": checksum,
                    "record_count": current_rows,
                    "batches": current_batches,
                }
            )
            chunk_index_by_state[current_state] = index + 1
            current_writer = None
            current_path = None
            current_rows = 0
            current_batches = []

        def start_chunk(state: str) -> None:
            nonlocal current_file, current_writer, current_path
            nonlocal current_state
            current_state = state
            index = chunk_index_by_state.setdefault(state, 0)
            safe_state = state.replace(" ", "_")
            current_path = staging_dir / f"{safe_state}_{index:05d}.csv"
            current_file = current_path.open(
                "w",
                encoding="utf-8",
                newline="",
            )
            current_writer = csv.writer(current_file)
            current_writer.writerow(COMPACT_HEADERS)

        try:
            for batch in source_batches:
                state = str(batch["state"])
                batch_rows = int(batch["record_count"])
                if batch_rows <= 0:
                    raise CompactionError(
                        f"Invalid record count for batch {batch['batch_id']}"
                    )
                if batch_rows > max_rows:
                    raise CompactionError(
                        f"Extraction batch {batch['batch_id']} has {batch_rows} "
                        f"rows, exceeding UDYAM_COMPACTION_MAX_ROWS={max_rows}"
                    )
                if current_file is not None and (
                    state != current_state or current_rows + batch_rows > max_rows
                ):
                    publish_chunk()
                if current_file is None:
                    start_chunk(state)

                local_batch = staging_dir / f"source_{len(compact_records)}_{batch['batch_id']}.csv"
                STORAGE.download_artifact(str(batch["batch_file"]), local_batch)
                if calculate_file_sha256(local_batch) != batch["checksum"]:
                    raise CompactionError(
                        f"Source batch checksum mismatch: {batch['batch_id']}"
                    )

                copied_rows = 0
                try:
                    with local_batch.open(
                        "r",
                        encoding="utf-8-sig",
                        newline="",
                    ) as source:
                        reader = csv.DictReader(source)
                        if reader.fieldnames != CSV_HEADERS:
                            raise CompactionError(
                                f"Unexpected CSV columns in batch {batch['batch_id']}"
                            )
                        for row in reader:
                            current_writer.writerow(
                                [row.get(column, "") or "" for column in CSV_HEADERS]
                                + [
                                    str(batch["batch_id"]),
                                    _stage_source_file(str(batch["batch_file"])),
                                    int(batch["offset"]),
                                ]
                            )
                            copied_rows += 1
                finally:
                    local_batch.unlink(missing_ok=True)

                if copied_rows != batch_rows:
                    raise CompactionError(
                        f"Batch row count mismatch for {batch['batch_id']}: "
                        f"manifest={batch_rows}, csv={copied_rows}"
                    )
                current_rows += copied_rows
                current_batches.append(
                    {
                        "batch_id": str(batch["batch_id"]),
                        "offset": int(batch["offset"]),
                        "record_count": batch_rows,
                        "checksum": str(batch["checksum"]),
                        "source_file": _stage_source_file(str(batch["batch_file"])),
                        "source_uri": str(batch["batch_file"]),
                    }
                )

            publish_chunk()
        finally:
            if current_file is not None and not current_file.closed:
                current_file.close()

    if not compact_records:
        raise CompactionError(f"No compacted files produced for run {run_id}")

    path = _write_compaction_manifest(run_id, compact_records)
    LOGGER.info(
        "Compaction completed: run_id=%s source_batches=%d "
        "compacted_files=%d max_rows_per_file=%d manifest=%s",
        run_id,
        len(source_batches),
        len(compact_records),
        max_rows,
        path,
    )
    return compact_records


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    run_id = os.getenv("UDYAM_RUN_ID", "").strip()
    if not run_id:
        LOGGER.error("UDYAM_RUN_ID must be set before compaction")
        return 1
    try:
        compact_run(run_id)
    except Exception:
        LOGGER.exception("Compaction failed for run_id=%s", run_id)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
