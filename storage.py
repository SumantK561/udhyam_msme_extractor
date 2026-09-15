"""Storage backends for Udyam RAW batch artifacts."""

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
import os


class StorageError(Exception):
    """Raised when a RAW storage operation fails."""


class LocalStorage:
    """Keep batch artifacts on the local filesystem."""

    def publish_batch(
        self,
        local_path: Path,
        run_id: str,
        state: str,
        offset: int,
        checksum: str,
    ) -> str:
        return str(local_path)

    def validate_artifact(self, manifest_record: dict, checksum_fn) -> tuple[bool, str]:
        batch_file = manifest_record.get("batch_file")
        expected_checksum = manifest_record.get("checksum")

        if not batch_file:
            return False, "MissingBatchFile"

        if not expected_checksum:
            return False, "MissingChecksum"

        path = Path(batch_file)

        if not path.exists():
            return False, "BatchFileNotFound"

        if not path.is_file():
            return False, "BatchPathNotFile"

        if path.stat().st_size <= 0:
            return False, "BatchFileEmpty"

        if checksum_fn(path) != expected_checksum:
            return False, "ChecksumMismatch"

        return True, ""

    def sync_manifest(self, run_id: str, local_path: Path) -> None:
        return None

    def sync_run_summary(self, run_id: str, local_path: Path) -> None:
        return None


class GCSStorage:
    """Publish RAW artifacts directly to Google Cloud Storage."""

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "udyam/raw",
        project: Optional[str] = None,
    ):
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise StorageError(
                "google-cloud-storage is required for "
                "UDYAM_STORAGE_BACKEND=gcs"
            ) from exc

        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")

        # ------------------------------------------------------------------
        # POC-ONLY authentication override.
        #
        # If UDYAM_GCS_ACCESS_TOKEN is present, use the explicitly supplied
        # OAuth access token. This is intended only for the current POC.
        #
        # Production should NOT use an access token in the environment.
        # Production authentication should use ADC / service account /
        # workload identity.
        # ------------------------------------------------------------------
        access_token = os.getenv("UDYAM_GCS_ACCESS_TOKEN")

        if access_token:
            try:
                from google.oauth2.credentials import Credentials

                credentials = Credentials(token=access_token)

            except Exception as exc:
                raise StorageError(
                    "Failed to initialize GCS credentials from "
                    "UDYAM_GCS_ACCESS_TOKEN"
                ) from exc

            self.client = storage.Client(
                project=project,
                credentials=credentials,
            )

        else:
            # Normal production/default authentication path.
            self.client = (
                storage.Client(project=project)
                if project
                else storage.Client()
            )

        self.bucket = self.client.bucket(bucket_name)

    def _object_name(
        self,
        run_id: str,
        state: str,
        filename: str,
        *,
        batch: bool = False,
    ) -> str:
        run_root = (
            f"{self.prefix}/run_id={run_id}"
            if self.prefix
            else f"run_id={run_id}"
        )

        if batch:
            return f"{run_root}/state={state}/batches/{filename}"

        return f"{run_root}/{filename}"

    def _uri(self, object_name: str) -> str:
        return f"gs://{self.bucket_name}/{object_name}"

    def publish_batch(
        self,
        local_path: Path,
        run_id: str,
        state: str,
        offset: int,
        checksum: str,
    ) -> str:
        object_name = self._object_name(
            run_id,
            state,
            local_path.name,
            batch=True,
        )

        blob = self.bucket.blob(object_name)

        blob.metadata = {
            "sha256": checksum,
        }

        try:
            with local_path.open("rb") as file:
                blob.upload_from_file(
                    file,
                    rewind=False,
                    checksum="auto",
                    if_generation_match=0,
                )

            blob.reload()

        except Exception as exc:
            raise StorageError(
                f"GCS upload failed for {self._uri(object_name)}: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Verify that the uploaded object exists and that its metadata
        # contains the expected checksum.
        # ------------------------------------------------------------------
        if blob.size is None or blob.size <= 0:
            raise StorageError(
                f"GCS upload verification failed: empty object "
                f"{self._uri(object_name)}"
            )

        remote_checksum = (blob.metadata or {}).get("sha256")

        if remote_checksum != checksum:
            raise StorageError(
                f"GCS checksum metadata mismatch for "
                f"{self._uri(object_name)}: "
                f"expected={checksum}, actual={remote_checksum}"
            )

        return self._uri(object_name)

    def validate_artifact(
        self,
        manifest_record: dict,
        checksum_fn,
    ) -> tuple[bool, str]:
        batch_file = manifest_record.get("batch_file")
        expected_checksum = manifest_record.get("checksum")

        if not batch_file:
            return False, "MissingBatchFile"

        if not expected_checksum:
            return False, "MissingChecksum"

        parsed = urlparse(batch_file)

        if parsed.scheme != "gs":
            return False, "InvalidGCSUri"

        if parsed.netloc != self.bucket_name:
            return False, "UnexpectedGCSBucket"

        object_name = parsed.path.lstrip("/")

        if not object_name:
            return False, "MissingGCSObject"

        blob = self.bucket.blob(object_name)

        try:
            blob.reload()

        except Exception:
            return False, "GCSObjectNotFound"

        if blob.size is None or blob.size <= 0:
            return False, "GCSObjectEmpty"

        remote_checksum = (blob.metadata or {}).get("sha256")

        if remote_checksum != expected_checksum:
            return False, "ChecksumMismatch"

        return True, ""

    def _upload_metadata_file(
        self,
        local_path: Path,
        object_name: str,
        content_type: str,
    ) -> None:
        blob = self.bucket.blob(object_name)

        try:
            with local_path.open("rb") as file:
                blob.upload_from_file(
                    file,
                    rewind=False,
                    content_type=content_type,
                    checksum="auto",
                )

            blob.reload()

        except Exception as exc:
            raise StorageError(
                f"GCS metadata upload failed for "
                f"{self._uri(object_name)}: {exc}"
            ) from exc

        if blob.size is None or blob.size <= 0:
            raise StorageError(
                f"GCS metadata upload verification failed: "
                f"empty object {self._uri(object_name)}"
            )

    def sync_manifest(
        self,
        run_id: str,
        local_path: Path,
    ) -> None:
        self._upload_metadata_file(
            local_path,
            self._object_name(
                run_id,
                "",
                local_path.name,
            ),
            "application/x-ndjson",
        )

    def sync_run_summary(
        self,
        run_id: str,
        local_path: Path,
    ) -> None:
        self._upload_metadata_file(
            local_path,
            self._object_name(
                run_id,
                "",
                local_path.name,
            ),
            "application/json",
        )


def build_storage(settings):
    """Build the configured RAW storage backend."""

    if settings.storage_backend == "gcs":
        return GCSStorage(
            bucket_name=settings.gcs_bucket,
            prefix=settings.gcs_prefix,
            project=settings.gcs_project,
        )

    return LocalStorage()