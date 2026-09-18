from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.models.schemas import (
    StatsResponse,
    StringListResponse,
    Supplier,
    SupplierListResponse,
)
from api.services.supplier_repository import supplier_repository


app = FastAPI(
    title="Supplier Explorer API",
    version="2.0.0",
    description="FastAPI backend for the Udyam Supplier Explorer",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "Supplier Explorer API is running",
        "status": "ok",
        "database": "Snowflake",
    }


@app.get("/health")
def health():
    try:
        stats = supplier_repository.get_stats()

        return {
            "status": "healthy",
            "database": "Snowflake",
            "total_suppliers": stats["total"],
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Snowflake connection failed: {exc}",
        )


@app.get(
    "/api/suppliers",
    response_model=SupplierListResponse,
)
def get_suppliers(
    search: str = "",
    state: str = "",
    district: str = "",
    pincode: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    try:
        return supplier_repository.search(
            search=search,
            state=state,
            district=district,
            pincode=pincode,
            page=page,
            page_size=page_size,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve suppliers: {exc}",
        )


@app.get(
    "/api/suppliers/{supplier_id}",
    response_model=Supplier,
)
def get_supplier(supplier_id: str):
    try:
        supplier = supplier_repository.get_by_id(
            supplier_id
        )

        if supplier is None:
            raise HTTPException(
                status_code=404,
                detail="Supplier not found",
            )

        return supplier

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve supplier: {exc}",
        )


@app.get(
    "/api/states",
    response_model=StringListResponse,
)
def get_states():
    try:
        return {
            "data": supplier_repository.get_states()
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve states: {exc}",
        )


@app.get(
    "/api/districts",
    response_model=StringListResponse,
)
def get_districts(state: str = ""):
    try:
        return {
            "data": supplier_repository.get_districts(
                state=state
            )
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve districts: {exc}",
        )


@app.get(
    "/api/stats",
    response_model=StatsResponse,
)
def get_stats():
    try:
        return supplier_repository.get_stats()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve statistics: {exc}",
        )
