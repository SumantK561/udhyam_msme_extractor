import os

import snowflake.connector
from dotenv import load_dotenv

load_dotenv()


class SnowflakeService:
    def __init__(self):
        self.account = os.getenv("SNOWFLAKE_ACCOUNT")
        self.user = os.getenv("SNOWFLAKE_USER")
        self.password = os.getenv("SNOWFLAKE_PASSWORD")
        self.authenticator = os.getenv(
            "SNOWFLAKE_AUTHENTICATOR",
            "snowflake",
        )
        self.role = os.getenv("SNOWFLAKE_ROLE")
        self.warehouse = os.getenv("SNOWFLAKE_WAREHOUSE")
        self.database = os.getenv("SNOWFLAKE_DATABASE")
        self.schema = os.getenv("SNOWFLAKE_SCHEMA")
        self.table = os.getenv(
            "SNOWFLAKE_RAW_TABLE",
            "MSME",
        )

    def connect(self):
        return snowflake.connector.connect(
            account=self.account,
            user=self.user,
            password=self.password,
            authenticator=self.authenticator,
            role=self.role,
            warehouse=self.warehouse,
            database=self.database,
            schema=self.schema,
        )

    @property
    def qualified_table(self):
        return (
            f'"{self.database}"'
            f'."{self.schema}"'
            f'."{self.table}"'
        )


snowflake_service = SnowflakeService()
