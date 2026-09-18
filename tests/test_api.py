import requests

BASE_URL = "http://127.0.0.1:8000"


def test_root():
    response = requests.get(f"{BASE_URL}/", timeout=30)

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["database"] == "Snowflake"


def test_health():
    response = requests.get(f"{BASE_URL}/health", timeout=30)

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "healthy"
    assert data["database"] == "Snowflake"
    assert data["total_suppliers"] > 0


def test_stats():
    response = requests.get(f"{BASE_URL}/api/stats", timeout=30)

    assert response.status_code == 200

    data = response.json()

    assert data["total"] > 0
    assert data["states"] > 0
    assert data["districts"] > 0


def test_states():
    response = requests.get(f"{BASE_URL}/api/states", timeout=30)

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data["data"], list)
    assert len(data["data"]) > 0


def test_districts():
    response = requests.get(f"{BASE_URL}/api/districts", timeout=30)

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data["data"], list)
    assert len(data["data"]) > 0


def test_supplier_search():
    response = requests.get(
        f"{BASE_URL}/api/suppliers",
        params={
            "search": "VINCENT",
            "page": 1,
            "page_size": 5,
        },
        timeout=30,
    )

    assert response.status_code == 200

    data = response.json()

    assert "data" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "total_pages" in data

    assert data["page"] == 1
    assert data["page_size"] == 5


def test_supplier_pagination():
    response = requests.get(
        f"{BASE_URL}/api/suppliers",
        params={
            "page": 1,
            "page_size": 10,
        },
        timeout=30,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["page"] == 1
    assert data["page_size"] == 10
    assert len(data["data"]) <= 10


def test_supplier_detail():
    response = requests.get(
        f"{BASE_URL}/api/suppliers",
        params={
            "search": "VINCENT",
            "page": 1,
            "page_size": 1,
        },
        timeout=30,
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data["data"]) > 0

    supplier_id = data["data"][0]["id"]

    detail_response = requests.get(
        f"{BASE_URL}/api/suppliers/{supplier_id}",
        timeout=30,
    )

    assert detail_response.status_code == 200

    detail = detail_response.json()

    assert detail["id"] == supplier_id
    assert "enterprise_name" in detail
    assert "state" in detail
    assert "district" in detail


def test_state_filter():
    response = requests.get(
        f"{BASE_URL}/api/suppliers",
        params={
            "state": "ANDAMAN AND NICOBAR ISLANDS",
            "page": 1,
            "page_size": 10,
        },
        timeout=30,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] > 0

    for supplier in data["data"]:
        assert supplier["state"] == "ANDAMAN AND NICOBAR ISLANDS"


def test_district_filter():
    response = requests.get(
        f"{BASE_URL}/api/suppliers",
        params={
            "district": "SOUTH ANDAMANS",
            "page": 1,
            "page_size": 10,
        },
        timeout=30,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] > 0

    for supplier in data["data"]:
        assert supplier["district"] == "SOUTH ANDAMANS"


def test_pincode_filter():
    response = requests.get(
        f"{BASE_URL}/api/suppliers",
        params={
            "pincode": "744105",
            "page": 1,
            "page_size": 10,
        },
        timeout=30,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] > 0

    for supplier in data["data"]:
        assert "744105" in str(supplier["pincode"])
