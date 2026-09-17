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


class ObjectStorage:
    """Object-store layout and verification shared by cloud backends.

    Subclasses provide the provider-specific calls (``_upload``, ``_head``)
    and set ``scheme``/``label``; everything else is identical across
    providers.
    """

    scheme = ""
    label = ""

    def __init__(self, bucket_name: str, prefix: str):
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")

    def _upload(
        self,
        local_path: Path,
        object_name: str,
        *,
        checksum: Optional[str] = None,
        content_type: Optional[str] = None,
        if_absent: bool = False,
    ) -> None:
        raise NotImplementedError

    def _head(
        self,
        object_name: str,
    ) -> Optional[tuple[Optional[int], Optional[str]]]:
        """Return (size, sha256 metadata), or None when the object is absent."""

        raise NotImplementedError

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
        return f"{self.scheme}://{self.bucket_name}/{object_name}"

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
        uri = self._uri(object_name)

        self._upload(
            local_path,
            object_name,
            checksum=checksum,
            if_absent=True,
        )

        # ------------------------------------------------------------------
        # Verify that the uploaded object exists and that its metadata
        # contains the expected checksum.
        # ------------------------------------------------------------------
        head = self._head(object_name)

        if head is None:
            raise StorageError(
                f"{self.label} upload verification failed: "
                f"missing object {uri}"
            )

        size, remote_checksum = head

        if not size:
            raise StorageError(
                f"{self.label} upload verification failed: empty object {uri}"
            )

        if remote_checksum != checksum:
            raise StorageError(
                f"{self.label} checksum metadata mismatch for {uri}: "
                f"expected={checksum}, actual={remote_checksum}"
            )

        return uri

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

        if parsed.scheme != self.scheme:
            return False, f"Invalid{self.label}Uri"

        if parsed.netloc != self.bucket_name:
            return False, f"Unexpected{self.label}Bucket"

        object_name = parsed.path.lstrip("/")

        if not object_name:
            return False, f"Missing{self.label}Object"

        head = self._head(object_name)

        if head is None:
            return False, f"{self.label}ObjectNotFound"

        size, remote_checksum = head

        if not size:
            return False, f"{self.label}ObjectEmpty"

        if remote_checksum != expected_checksum:
            return False, "ChecksumMismatch"

        return True, ""

    def _upload_metadata_file(
        self,
        local_path: Path,
        object_name: str,
        content_type: str,
    ) -> None:
        self._upload(
            local_path,
            object_name,
            content_type=content_type,
        )

        head = self._head(object_name)

        if head is None or not head[0]:
            raise StorageError(
                f"{self.label} metadata upload verification failed: "
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


class GCSStorage(ObjectStorage):
    """Publish RAW artifacts directly to Google Cloud Storage."""

    scheme = "gs"
    label = "GCS"

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "udyam/raw",
        project: Optional[str] = None,
    ):
        super().__init__(bucket_name, prefix)

        try:
            from google.cloud import storage
        except ImportError as exc:
            raise StorageError(
                "google-cloud-storage is required for "
                "UDYAM_STORAGE_BACKEND=gcs"
            ) from exc

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


    def _upload(
        self,
        local_path: Path,
        object_name: str,
        *,
        checksum: Optional[str] = None,
        content_type: Optional[str] = None,
        if_absent: bool = False,
    ) -> None:
        blob = self.bucket.blob(object_name)

        if checksum:
            blob.metadata = {
                "sha256": checksum,
            }

        options = {}

        if content_type:
            options["content_type"] = content_type

        if if_absent:
            options["if_generation_match"] = 0

        try:
            with local_path.open("rb") as file:
                blob.upload_from_file(
                    file,
                    rewind=False,
                    checksum="auto",
                    **options,
                )

        except Exception as exc:
            raise StorageError(
                f"GCS upload failed for {self._uri(object_name)}: {exc}"
            ) from exc

    def _head(
        self,
        object_name: str,
    ) -> Optional[tuple[Optional[int], Optional[str]]]:
        blob = self.bucket.blob(object_name)

        try:
            blob.reload()

        except Exception:
            return None

        return blob.size, (blob.metadata or {}).get("sha256")


class S3Storage(ObjectStorage):
    """Publish RAW artifacts directly to Amazon S3."""

    scheme = "s3"
    label = "S3"

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "udyam/raw",
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        super().__init__(bucket_name, prefix)

        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError as exc:
            raise StorageError(
                "boto3 is required for UDYAM_STORAGE_BACKEND=s3"
            ) from exc

        self._client_error = ClientError

        # Credentials come from the default AWS chain: environment,
        # shared config, or instance/task role.
        self.client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
        )

    def _upload(
        self,
        local_path: Path,
        object_name: str,
        *,
        checksum: Optional[str] = None,
        content_type: Optional[str] = None,
        if_absent: bool = False,
    ) -> None:
        options = {}

        if checksum:
            options["Metadata"] = {
                "sha256": checksum,
            }

        if content_type:
            options["ContentType"] = content_type

        if if_absent:
            options["IfNoneMatch"] = "*"

        try:
            with local_path.open("rb") as file:
                self.client.put_object(
                    Bucket=self.bucket_name,
                    Key=object_name,
                    Body=file,
                    **options,
                )

        except Exception as exc:
            raise StorageError(
                f"S3 upload failed for {self._uri(object_name)}: {exc}"
            ) from exc

    def _head(
        self,
        object_name: str,
    ) -> Optional[tuple[Optional[int], Optional[str]]]:
        try:
            response = self.client.head_object(
                Bucket=self.bucket_name,
                Key=object_name,
            )

        except self._client_error:
            return None

        metadata = response.get("Metadata") or {}

        return response.get("ContentLength"), metadata.get("sha256")


def build_storage(settings):
    """Build the configured RAW storage backend."""

    if settings.storage_backend == "gcs":
        return GCSStorage(
            bucket_name=settings.gcs_bucket,
            prefix=settings.gcs_prefix,
            project=settings.gcs_project,
        )

    if settings.storage_backend == "s3":
        return S3Storage(
            bucket_name=settings.s3_bucket,
            prefix=settings.s3_prefix,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
        )

    return LocalStorage()
