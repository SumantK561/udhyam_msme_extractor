"""
Bi-weekly incremental pipeline: extract new MSME records → Snowflake → dbt.

Schedule: every 14 days from the anchor start_date below (cron has no
native "every 2 weeks" -- a fixed timedelta interval is the reliable way
to express it in Airflow).
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
    description="Bi-weekly incremental MSME extraction → Snowflake → dbt",
    schedule_interval=timedelta(days=14),
    start_date=datetime(2026, 9, 21),
    catchup=False,
    tags=["udyam", "msme", "incremental"],
) as dag:

    extract = BashOperator(
        task_id="extract",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR} && "
            "python3 -c \""
            "from udyam_extractor import get_run_id; "
            "rid = get_run_id(); "
            "open('/tmp/udyam_run_id.txt', 'w').write(rid); "
            "print('RUN_ID:', rid)"
            "\" && "
            "export UDYAM_RUN_ID=$(cat /tmp/udyam_run_id.txt) && "
            "python3 run_udyam.py"
        ),
        execution_timeout=timedelta(hours=10),
    )

    load = BashOperator(
        task_id="load_to_snowflake",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR} && "
            "export UDYAM_RUN_ID=$(cat /tmp/udyam_run_id.txt) && "
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
