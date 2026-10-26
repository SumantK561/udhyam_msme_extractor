import csv
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import scripts.compact_batches as compactor
from udyam_extractor import CSV_HEADERS


class FakeStorage:
    def __init__(self, source_files, published):
        self.source_files = source_files
        self.published = published
        self.downloads = 0

    def download_artifact(self, batch_file, local_path):
        self.downloads += 1
        shutil.copyfile(self.source_files[batch_file], local_path)

    def publish_batch(self, local_path, run_id, state, offset, checksum):
        batch_file = (
            f"s3://bucket/udyam/raw/run_id={run_id}/state={state}/"
            f"batches/{local_path.name}"
        )
        self.published[batch_file] = (local_path.read_bytes(), checksum)
        return batch_file

    def publish_compacted_batch(self, local_path, run_id, state, offset, checksum):
        return self.publish_batch(local_path, run_id, state, offset, checksum)

    def validate_artifact(self, record, checksum_fn):
        item = self.published.get(record["batch_file"])
        return (item is not None and item[1] == record["checksum"], "")

    def sync_compaction_manifest(self, run_id, local_path):
        return None


def _write_batch(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def test_compact_run_groups_batches_with_row_bound(tmp_path, monkeypatch):
    run_id = "RUN1"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    source_files = {}
    manifest = []
    for offset, names in ((0, ["Alpha", "Beta"]), (2, ["Gamma", "Delta"])):
        source_path = tmp_path / f"source_{offset}.csv"
        rows = [
            {
                "LG_ST_Code": "1",
                "State": "GOA",
                "LG_DT_Code": "2",
                "District": "NORTH",
                "Pincode": "403001",
                "RegistrationDate": "01/01/2026",
                "EnterpriseName": name,
                "CommunicationAddress": "",
                "Activities": "[]",
            }
            for name in names
        ]
        _write_batch(source_path, rows)
        batch_file = (
            f"s3://bucket/udyam/raw/run_id={run_id}/state=GOA/"
            f"batches/{run_id}_GOA_{offset}.csv"
        )
        source_files[batch_file] = source_path
        manifest.append(
            {
                "batch_id": f"{run_id}_GOA_{offset}",
                "run_id": run_id,
                "state": "GOA",
                "offset": offset,
                "record_count": len(rows),
                "batch_file": batch_file,
                "checksum": compactor.calculate_file_sha256(source_path),
                "status": "SUCCESS",
            }
        )
    (run_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in manifest),
        encoding="utf-8",
    )
    published = {}
    storage = FakeStorage(source_files, published)
    monkeypatch.setattr(compactor, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(compactor, "STORAGE", storage)
    monkeypatch.setattr(
        compactor,
        "SETTINGS",
        SimpleNamespace(compaction_max_rows=3),
    )

    compacted = compactor.compact_run(run_id)

    assert len(compacted) == 2
    assert [entry["record_count"] for entry in compacted] == [2, 2]
    assert [len(entry["batches"]) for entry in compacted] == [1, 1]
    for entry in compacted:
        content, checksum = published[entry["batch_file"]]
        assert checksum == entry["checksum"]
        rows = list(csv.DictReader(content.decode("utf-8").splitlines()))
        assert len(rows) == entry["record_count"]
        assert rows[0]["__BATCH_ID"] == entry["batches"][0]["batch_id"]
        assert rows[0]["__SOURCE_OFFSET"] == str(entry["batches"][0]["offset"])
        assert rows[0]["__SOURCE_FILE"].startswith("udyam/raw/run_id=RUN1/")


def test_compaction_retry_reuses_verified_artifacts(tmp_path, monkeypatch):
    run_id = "RUN2"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    source_path = tmp_path / "source.csv"
    _write_batch(
        source_path,
        [
            {
                "LG_ST_Code": "1",
                "State": "GOA",
                "LG_DT_Code": "2",
                "District": "NORTH",
                "Pincode": "403001",
                "RegistrationDate": "01/01/2026",
                "EnterpriseName": "Alpha",
                "CommunicationAddress": "",
                "Activities": "[]",
            }
        ],
    )
    batch_file = (
        f"s3://bucket/udyam/raw/run_id={run_id}/state=GOA/"
        f"batches/{run_id}_GOA_0.csv"
    )
    batch = {
        "batch_id": f"{run_id}_GOA_0",
        "run_id": run_id,
        "state": "GOA",
        "offset": 0,
        "record_count": 1,
        "batch_file": batch_file,
        "checksum": compactor.calculate_file_sha256(source_path),
        "status": "SUCCESS",
    }
    (run_dir / "manifest.jsonl").write_text(
        json.dumps(batch) + "\n",
        encoding="utf-8",
    )
    storage = FakeStorage({batch_file: source_path}, {})
    monkeypatch.setattr(compactor, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(compactor, "STORAGE", storage)
    monkeypatch.setattr(
        compactor,
        "SETTINGS",
        SimpleNamespace(compaction_max_rows=10),
    )

    first = compactor.compact_run(run_id)
    downloads_after_first_run = storage.downloads
    second = compactor.compact_run(run_id)

    assert second == first
    assert storage.downloads == downloads_after_first_run
