"""
Weekly incremental pipeline: extract new MSME records → Snowflake → dbt.

Schedule: every Sunday at midnight UTC.
Each run picks up only records added since the previous run (new registrations).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/home/ubuntu/udhyam_msme_extractor"
VENV = f"{PROJECT_DIR}/.venv/bin/activate"

default_args = {
    "owner": "udyam",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
}

with DAG(
    dag_id="udyam_incremental_pipeline",
    default_args=default_args,
    description="Weekly incremental MSME extraction → Snowflake → dbt",
    schedule_interval="0 0 * * 0",
    start_date=datetime(2026, 9, 21),
    catchup=False,
    tags=["udyam", "msme", "incremental"],
) as dag:

    extract = BashOperator(
        task_id="extract",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR} && "
            "python3 run_udyam.py"
        ),
        execution_timeout=timedelta(hours=10),
    )

    load = BashOperator(
        task_id="load_to_snowflake",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR} && "
            "python3 scripts/load_to_snowflake.py"
        ),
        execution_timeout=timedelta(hours=3),
    )

    transform = BashOperator(
        task_id="dbt_run",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR}/udyam_dbt && "
            "dbt run"
        ),
        execution_timeout=timedelta(hours=2),
    )

    extract >> load >> transform
