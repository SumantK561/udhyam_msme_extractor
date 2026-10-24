"""
Bi-weekly incremental pipeline: extract new MSME records → Snowflake → dbt.

Schedule: 1st and 15th of every month at midnight UTC.
Each run picks up only records added since the previous run (new registrations).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from airflow import DAG
from airflow.models import Variable
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

PROJECT_DIR = "/home/ubuntu/udhyam_msme_extractor"
VENV = f"{PROJECT_DIR}/.venv/bin/activate"
ACTIVE_RUN_ID_VARIABLE = "udyam_incremental_active_run_id"
LOGGER = logging.getLogger(__name__)

default_args = {
    "owner": "udyam",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
}


def get_or_create_run_id() -> str:
    """Reuse the active extraction ID, or persist a new one for this pipeline."""
    run_id = Variable.get(ACTIVE_RUN_ID_VARIABLE, default_var=None)
    if run_id:
        LOGGER.info("Reusing active Udyam run ID: %s", run_id)
        return run_id

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}_{uuid4().hex[:8]}"
    Variable.set(ACTIVE_RUN_ID_VARIABLE, run_id)
    LOGGER.info("Created active Udyam run ID: %s", run_id)
    return run_id


def clear_run_id_after_success(ti) -> None:
    """Clear the active ID only after every pipeline stage has succeeded."""
    run_id = ti.xcom_pull(task_ids="get_or_create_run_id")
    if not run_id:
        raise RuntimeError("Could not retrieve the active Udyam run ID from XCom")

    active_run_id = Variable.get(ACTIVE_RUN_ID_VARIABLE, default_var=None)
    if active_run_id is None:
        return
    if active_run_id != run_id:
        raise RuntimeError(
            "Refusing to clear a different active Udyam run ID: "
            f"expected {run_id}, found {active_run_id}"
        )

    Variable.delete(ACTIVE_RUN_ID_VARIABLE)
    LOGGER.info("Cleared completed Udyam run ID: %s", run_id)


with DAG(
    dag_id="udyam_incremental_pipeline",
    default_args=default_args,
    description="Bi-weekly incremental MSME extraction → Snowflake → dbt",
    schedule_interval="0 0 1,15 * *",  # 1st and 15th of every month at midnight UTC
    start_date=datetime(2026, 9, 21),
    catchup=False,
    max_active_runs=1,
    tags=["udyam", "msme", "incremental"],
) as dag:

    get_run_id = PythonOperator(
        task_id="get_or_create_run_id",
        python_callable=get_or_create_run_id,
    )

    extract = BashOperator(
        task_id="extract",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR} && "
            "export UDYAM_RUN_ID='{{ ti.xcom_pull(task_ids=\"get_or_create_run_id\") }}' && "
            "python3 run_udyam.py"
        ),
        execution_timeout=timedelta(hours=48),
    )

    load = BashOperator(
        task_id="load_to_snowflake",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR} && "
            "export UDYAM_RUN_ID='{{ ti.xcom_pull(task_ids=\"get_or_create_run_id\") }}' && "
            "python3 scripts/load_to_snowflake.py"
        ),
        execution_timeout=timedelta(hours=48),
    )

    transform = BashOperator(
        task_id="dbt_run",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR}/udyam_dbt && "
            "dbt run"
        ),
        execution_timeout=timedelta(hours=48),
    )

    docs = BashOperator(
        task_id="dbt_docs_generate",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR}/udyam_dbt && "
            "dbt docs generate"
        ),
        execution_timeout=timedelta(hours=2),
    )

    clear_run_id = PythonOperator(
        task_id="clear_run_id_after_success",
        python_callable=clear_run_id_after_success,
    )

    get_run_id >> extract >> load >> transform >> docs >> clear_run_id
