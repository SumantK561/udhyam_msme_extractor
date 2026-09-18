import base64
import hashlib
import json

from api.services.snowflake import snowflake_service


class SupplierRepository:

    def _make_supplier_id(self, row):
        """
        Create a stable opaque ID from the supplier's business fields.

        The ID contains the values needed to perform an exact,
        parameterized Snowflake lookup later. No database credentials
        or secrets are included.
        """
        values = [
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
        ]

        raw = "|".join(
            "" if value is None else str(value)
            for value in values
        )

        encoded = base64.urlsafe_b64encode(
            raw.encode("utf-8")
        ).decode("ascii")

        return encoded.rstrip("=")

    def _decode_supplier_id(self, supplier_id):
        """
        Decode the opaque supplier ID back into the eight
        business-field values used to identify the record.
        """
        padding = "=" * (-len(supplier_id) % 4)

        decoded = base64.urlsafe_b64decode(
            supplier_id + padding
        ).decode("utf-8")

        values = decoded.split("|")

        if len(values) != 8:
            raise ValueError("Invalid supplier ID")

        return [
            value if value != "" else None
            for value in values
        ]

    def _row_to_supplier(self, row):
        activities = row[8]

        if isinstance(activities, str):
            try:
                activities = json.loads(activities)
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "id": self._make_supplier_id(row),
            "lg_st_code": row[0],
            "state": row[1],
            "lg_dt_code": row[2],
            "district": row[3],
            "pincode": row[4],
            "registration_date": row[5],
            "enterprise_name": row[6],
            "communication_address": row[7],
            "activities": activities,
            "run_id": row[9],
            "source_state": row[10],
            "batch_id": row[11],
            "source_file": row[12],
            "source_offset": row[13],
            "ingested_at": row[14],
        }

    def _build_filters(
        self,
        search="",
        state="",
        district="",
        pincode="",
    ):
        conditions = []
        params = []

        if search:
            conditions.append(
                """
                (
                    UPPER(ENTERPRISE_NAME) LIKE UPPER(%s)
                    OR UPPER(DISTRICT) LIKE UPPER(%s)
                    OR UPPER(STATE) LIKE UPPER(%s)
                    OR PINCODE LIKE %s
                    OR UPPER(COMMUNICATION_ADDRESS)
                       LIKE UPPER(%s)
                )
                """
            )

            value = f"%{search}%"

            params.extend(
                [
                    value,
                    value,
                    value,
                    value,
                    value,
                ]
            )

        if state:
            conditions.append(
                "UPPER(STATE) = UPPER(%s)"
            )
            params.append(state)

        if district:
            conditions.append(
                "UPPER(DISTRICT) = UPPER(%s)"
            )
            params.append(district)

        if pincode:
            conditions.append(
                "PINCODE LIKE %s"
            )
            params.append(f"%{pincode}%")

        return conditions, params

    def search(
        self,
        search="",
        state="",
        district="",
        pincode="",
        page=1,
        page_size=10,
    ):
        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)

        conditions, params = self._build_filters(
            search,
            state,
            district,
            pincode,
        )

        where_clause = ""

        if conditions:
            where_clause = (
                "WHERE " + " AND ".join(conditions)
            )

        offset = (page - 1) * page_size

        count_sql = f"""
            SELECT COUNT(*)
            FROM {snowflake_service.qualified_table}
            {where_clause}
        """

        data_sql = f"""
            SELECT
                LG_ST_CODE,
                STATE,
                LG_DT_CODE,
                DISTRICT,
                PINCODE,
                REGISTRATION_DATE,
                ENTERPRISE_NAME,
                COMMUNICATION_ADDRESS,
                ACTIVITIES,
                _RUN_ID,
                _STATE,
                _BATCH_ID,
                _SOURCE_FILE,
                _SOURCE_OFFSET,
                _INGESTED_AT
            FROM {snowflake_service.qualified_table}
            {where_clause}
            ORDER BY ENTERPRISE_NAME, DISTRICT, PINCODE
            LIMIT %s OFFSET %s
        """

        conn = snowflake_service.connect()

        try:
            cursor = conn.cursor()

            try:
                cursor.execute(
                    count_sql,
                    tuple(params),
                )

                total = cursor.fetchone()[0]

                cursor.execute(
                    data_sql,
                    tuple(
                        params + [
                            page_size,
                            offset,
                        ]
                    ),
                )

                rows = cursor.fetchall()

                data = [
                    self._row_to_supplier(row)
                    for row in rows
                ]

                total_pages = (
                    (total + page_size - 1)
                    // page_size
                    if total
                    else 1
                )

                return {
                    "data": data,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                }

            finally:
                cursor.close()

        finally:
            conn.close()

    def get_by_id(self, supplier_id):
        """
        Retrieve one supplier directly from Snowflake.

        The previous implementation downloaded the entire table into
        Python and searched locally. This implementation decodes the
        supplier ID and performs an exact parameterized SQL lookup.
        """

        values = self._decode_supplier_id(supplier_id)

        sql = f"""
            SELECT
                LG_ST_CODE,
                STATE,
                LG_DT_CODE,
                DISTRICT,
                PINCODE,
                REGISTRATION_DATE,
                ENTERPRISE_NAME,
                COMMUNICATION_ADDRESS,
                ACTIVITIES,
                _RUN_ID,
                _STATE,
                _BATCH_ID,
                _SOURCE_FILE,
                _SOURCE_OFFSET,
                _INGESTED_AT
            FROM {snowflake_service.qualified_table}
            WHERE LG_ST_CODE IS NOT DISTINCT FROM %s
              AND STATE IS NOT DISTINCT FROM %s
              AND LG_DT_CODE IS NOT DISTINCT FROM %s
              AND DISTRICT IS NOT DISTINCT FROM %s
              AND PINCODE IS NOT DISTINCT FROM %s
              AND REGISTRATION_DATE IS NOT DISTINCT FROM %s
              AND ENTERPRISE_NAME IS NOT DISTINCT FROM %s
              AND COMMUNICATION_ADDRESS IS NOT DISTINCT FROM %s
            LIMIT 1
        """

        conn = snowflake_service.connect()

        try:
            cursor = conn.cursor()

            try:
                cursor.execute(
                    sql,
                    tuple(values),
                )

                row = cursor.fetchone()

                if row is None:
                    return None

                return self._row_to_supplier(row)

            finally:
                cursor.close()

        finally:
            conn.close()

    def get_states(self):
        sql = f"""
            SELECT DISTINCT STATE
            FROM {snowflake_service.qualified_table}
            WHERE STATE IS NOT NULL
              AND TRIM(STATE) <> ''
            ORDER BY STATE
        """

        conn = snowflake_service.connect()

        try:
            cursor = conn.cursor()

            try:
                cursor.execute(sql)

                return [
                    row[0]
                    for row in cursor.fetchall()
                ]

            finally:
                cursor.close()

        finally:
            conn.close()

    def get_districts(self, state=""):
        if state:
            sql = f"""
                SELECT DISTINCT DISTRICT
                FROM {snowflake_service.qualified_table}
                WHERE UPPER(STATE) = UPPER(%s)
                  AND DISTRICT IS NOT NULL
                  AND TRIM(DISTRICT) <> ''
                ORDER BY DISTRICT
            """

            params = (state,)

        else:
            sql = f"""
                SELECT DISTINCT DISTRICT
                FROM {snowflake_service.qualified_table}
                WHERE DISTRICT IS NOT NULL
                  AND TRIM(DISTRICT) <> ''
                ORDER BY DISTRICT
            """

            params = ()

        conn = snowflake_service.connect()

        try:
            cursor = conn.cursor()

            try:
                cursor.execute(sql, params)

                return [
                    row[0]
                    for row in cursor.fetchall()
                ]

            finally:
                cursor.close()

        finally:
            conn.close()

    def get_stats(self):
        sql = f"""
            SELECT
                COUNT(*) AS TOTAL,
                COUNT(DISTINCT STATE) AS STATES,
                COUNT(DISTINCT DISTRICT) AS DISTRICTS
            FROM {snowflake_service.qualified_table}
        """

        conn = snowflake_service.connect()

        try:
            cursor = conn.cursor()

            try:
                cursor.execute(sql)

                row = cursor.fetchone()

                return {
                    "total": row[0],
                    "states": row[1],
                    "districts": row[2],
                }

            finally:
                cursor.close()

        finally:
            conn.close()


supplier_repository = SupplierRepository()