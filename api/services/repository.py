from api.services.data import get_all_enterprises


class EnterpriseRepository:
    """
    Data-access layer for Udyam enterprises.

    Currently uses the local demo dataset.
    This can later be replaced with AWS/Snowflake-backed
    queries without changing the API routes.
    """

    def get_all(self):
        return get_all_enterprises()

    def get_by_id(self, enterprise_id):
        enterprises = self.get_all()

        for enterprise in enterprises:
            if enterprise["id"] == enterprise_id:
                return enterprise

        return None
