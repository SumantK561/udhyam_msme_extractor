from typing import Any

from pydantic import BaseModel


class Supplier(BaseModel):
    id: str
    lg_st_code: str | None = None
    state: str | None = None
    lg_dt_code: str | None = None
    district: str | None = None
    pincode: str | None = None
    registration_date: str | None = None
    enterprise_name: str | None = None
    communication_address: str | None = None
    activities: Any = None
    run_id: str | None = None
    source_state: str | None = None
    batch_id: str | None = None
    source_file: str | None = None
    source_offset: int | None = None
    ingested_at: Any = None


class SupplierListResponse(BaseModel):
    data: list[Supplier]
    total: int
    page: int
    page_size: int
    total_pages: int


class StatsResponse(BaseModel):
    total: int
    states: int
    districts: int


class StringListResponse(BaseModel):
    data: list[str]
