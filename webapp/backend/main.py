"""Public MSME search API.

Read-only FastAPI service over the UDYAM.RAW_GOLD star schema. Runs
against the UDYAM_PUBLIC_READER Snowflake role on a dedicated warehouse
(UDYAM_PUBLIC_WH) so public traffic never touches RAW/BRONZE/SILVER or
contends with the ETL pipeline's warehouse.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cache import TTLCache
from snowflake_client import get_connection

load_dotenv()

logging.basicConfig(level=os.getenv("UDYAM_WEB_LOG_LEVEL", "INFO"))
logger = logging.getLogger("udyam.webapp")

MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 20
LOOKUP_CACHE_TTL_SECONDS = 6 * 60 * 60  # states/districts/NIC codes rarely change

app = FastAPI(title="Udyam MSME Search API", version="1.0.0")

_cors_origins = [o.strip() for o in os.getenv("UDYAM_WEB_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

_lookup_cache = TTLCache(ttl_seconds=LOOKUP_CACHE_TTL_SECONDS)


class Enterprise(BaseModel):
    enterprise_key: str
    enterprise_name: str
    communication_address: Optional[str] = None
    state_name: Optional[str] = None
    district_name: Optional[str] = None
    pincode: Optional[str] = None
    registration_date: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[Enterprise]
    page: int
    page_size: int
    has_next: bool


class NicCode(BaseModel):
    nic_code: str
    nic_description: Optional[str] = None


class EnterpriseDetail(Enterprise):
    activities: list[NicCode]


def _run_query(sql: str, params: dict) -> list[tuple]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/meta/states")
def list_states():
    def compute():
        rows = _run_query(
            "SELECT DISTINCT state_name FROM DIM_GEOGRAPHY "
            "WHERE state_name IS NOT NULL ORDER BY state_name",
            {},
        )
        return [r[0] for r in rows]

    return _lookup_cache.get_or_set("states", compute)


@app.get("/api/meta/districts")
def list_districts(state: str = Query(..., min_length=1)):
    def compute():
        rows = _run_query(
            "SELECT DISTINCT district_name FROM DIM_GEOGRAPHY "
            "WHERE state_name = %(state)s AND district_name IS NOT NULL "
            "ORDER BY district_name",
            {"state": state},
        )
        return [r[0] for r in rows]

    return _lookup_cache.get_or_set(("districts", state), compute)


@app.get("/api/meta/nic-codes")
def list_nic_codes():
    def compute():
        rows = _run_query(
            "SELECT nic_code, nic_description FROM DIM_NIC_CODE "
            "ORDER BY nic_code",
            {},
        )
        return [{"nic_code": r[0], "nic_description": r[1]} for r in rows]

    return _lookup_cache.get_or_set("nic_codes", compute)


@app.get("/api/search", response_model=SearchResponse)
def search(
    name: Optional[str] = Query(None, min_length=2, max_length=200),
    state: Optional[str] = Query(None, max_length=100),
    district: Optional[str] = Query(None, max_length=100),
    nic_code: Optional[str] = Query(None, max_length=10),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    if not any([name, state, district, nic_code]):
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of: name, state, district, nic_code.",
        )

    clauses = ["1=1"]
    params: dict = {}

    if name:
        clauses.append("e.enterprise_name ILIKE %(name_pattern)s")
        params["name_pattern"] = f"%{name}%"
    if state:
        clauses.append("e.state_name = %(state)s")
        params["state"] = state
    if district:
        clauses.append("e.district_name = %(district)s")
        params["district"] = district
    if nic_code:
        clauses.append(
            "e.enterprise_key IN "
            "(SELECT enterprise_key FROM BRIDGE_ENTERPRISE_ACTIVITY WHERE nic_code = %(nic_code)s)"
        )
        params["nic_code"] = nic_code

    offset = (page - 1) * page_size
    params["limit"] = page_size + 1  # fetch one extra to detect has_next cheaply
    params["offset"] = offset

    sql = f"""
        SELECT
            e.enterprise_key,
            e.enterprise_name,
            e.communication_address,
            e.state_name,
            e.district_name,
            e.pincode,
            e.registration_date
        FROM DIM_ENTERPRISE e
        WHERE {' AND '.join(clauses)}
        ORDER BY e.enterprise_name
        LIMIT %(limit)s OFFSET %(offset)s
    """

    try:
        rows = _run_query(sql, params)
    except Exception:
        logger.exception("Search query failed")
        raise HTTPException(status_code=502, detail="Search temporarily unavailable.")

    has_next = len(rows) > page_size
    rows = rows[:page_size]

    results = [
        Enterprise(
            enterprise_key=r[0],
            enterprise_name=r[1],
            communication_address=r[2],
            state_name=r[3],
            district_name=r[4],
            pincode=r[5],
            registration_date=str(r[6]) if r[6] else None,
        )
        for r in rows
    ]

    return SearchResponse(results=results, page=page, page_size=page_size, has_next=has_next)


@app.get("/api/enterprise/{enterprise_key}", response_model=EnterpriseDetail)
def get_enterprise(enterprise_key: str):
    rows = _run_query(
        """
        SELECT enterprise_key, enterprise_name, communication_address,
               state_name, district_name, pincode, registration_date
        FROM DIM_ENTERPRISE
        WHERE enterprise_key = %(key)s
        """,
        {"key": enterprise_key},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Enterprise not found.")

    r = rows[0]
    activities = _run_query(
        "SELECT nic_code, nic_description FROM BRIDGE_ENTERPRISE_ACTIVITY "
        "WHERE enterprise_key = %(key)s ORDER BY nic_code",
        {"key": enterprise_key},
    )

    return EnterpriseDetail(
        enterprise_key=r[0],
        enterprise_name=r[1],
        communication_address=r[2],
        state_name=r[3],
        district_name=r[4],
        pincode=r[5],
        registration_date=str(r[6]) if r[6] else None,
        activities=[NicCode(nic_code=a[0], nic_description=a[1]) for a in activities],
    )
