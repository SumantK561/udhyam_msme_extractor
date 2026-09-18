"""Runtime configuration for the Udyam MSME extractor."""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


def _get_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default

    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc

    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")

    return value


def _get_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default

    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc

    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")

    return value


def _get_test_state() -> Optional[str]:
    value = os.getenv(
        "UDYAM_TEST_STATE",
        "ANDAMAN AND NICOBAR ISLANDS",
    ).strip()

    if not value or value.upper() == "ALL":
        return None

    return value


@dataclass(frozen=True)
class Settings:
    api_key: Optional[str]
    test_state: Optional[str]
    max_workers: int
    batch_size: int
    max_retries: int
    connect_timeout: int
    max_request_time: int
    retry_backoff_base: float
    retry_backoff_max: float
    retry_jitter: float
    rate_limit_delay: float
    log_level: str

    # Storage configuration
    storage_provider: str

    # Google Cloud Storage
    gcs_bucket: Optional[str]
    gcs_prefix: str
    gcs_project: Optional[str]

    # AWS S3
    aws_s3_bucket: Optional[str]
    aws_s3_prefix: str
    aws_region: Optional[str]


def load_settings() -> Settings:
    """Load and validate runtime configuration from environment/.env."""

    load_dotenv()

    settings = Settings(
        api_key=os.getenv("UDYAM_API_KEY"),
        test_state=_get_test_state(),

        max_workers=_get_int("UDYAM_MAX_WORKERS", 3),
        batch_size=_get_int("UDYAM_BATCH_SIZE", 10000),
        max_retries=_get_int("UDYAM_MAX_RETRIES", 5),

        connect_timeout=_get_int("UDYAM_CONNECT_TIMEOUT", 30),
        max_request_time=_get_int("UDYAM_MAX_REQUEST_TIME", 300),

        retry_backoff_base=_get_float(
            "UDYAM_RETRY_BACKOFF_BASE",
            5.0,
        ),
        retry_backoff_max=_get_float(
            "UDYAM_RETRY_BACKOFF_MAX",
            60.0,
        ),
        retry_jitter=_get_float(
            "UDYAM_RETRY_JITTER",
            3.0,
        ),
        rate_limit_delay=_get_float(
            "UDYAM_RATE_LIMIT_DELAY",
            30.0,
        ),

        log_level=os.getenv(
            "UDYAM_LOG_LEVEL",
            "INFO",
        ).upper(),

        # Storage provider:
        # local / gcs / aws
        storage_provider=os.getenv(
            "STORAGE_PROVIDER",
            "local",
        ).strip().lower(),

        # GCS
        gcs_bucket=os.getenv(
            "UDYAM_GCS_BUCKET"
        ) or None,

        gcs_prefix=os.getenv(
            "UDYAM_GCS_PREFIX",
            "udyam/raw",
        ).strip("/"),

        gcs_project=os.getenv(
            "UDYAM_GCS_PROJECT"
        ) or None,

        # AWS S3
        aws_s3_bucket=os.getenv(
            "AWS_S3_BUCKET"
        ) or None,

        aws_s3_prefix=os.getenv(
            "AWS_S3_PREFIX",
            "udyam/raw",
        ).strip("/"),

        aws_region=os.getenv(
            "AWS_REGION"
        ) or None,
    )

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    if settings.batch_size <= 0:
        raise ValueError(
            "UDYAM_BATCH_SIZE must be > 0"
        )

    if settings.retry_backoff_max < settings.retry_backoff_base:
        raise ValueError(
            "UDYAM_RETRY_BACKOFF_MAX must be >= "
            "UDYAM_RETRY_BACKOFF_BASE"
        )

    if settings.storage_provider not in {
        "local",
        "gcs",
        "aws",
    }:
        raise ValueError(
            "STORAGE_PROVIDER must be local, gcs, or aws"
        )

    # GCS validation
    if (
        settings.storage_provider == "gcs"
        and not settings.gcs_bucket
    ):
        raise ValueError(
            "UDYAM_GCS_BUCKET is required when "
            "STORAGE_PROVIDER=gcs"
        )

    # AWS validation
    if (
        settings.storage_provider == "aws"
        and not settings.aws_s3_bucket
    ):
        raise ValueError(
            "AWS_S3_BUCKET is required when "
            "STORAGE_PROVIDER=aws"
        )

    if settings.log_level not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }:
        raise ValueError(
            "UDYAM_LOG_LEVEL must be DEBUG, INFO, "
            "WARNING, ERROR, or CRITICAL"
        )

    return settings