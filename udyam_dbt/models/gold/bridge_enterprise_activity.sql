-- One row per enterprise x NIC code. Bridges dim_enterprise and dim_nic_code
-- so downstream consumers (e.g. the public search API) can query NIC codes
-- without needing access to the Silver schema.

SELECT
    a.enterprise_key,
    n.nic_key,
    a.nic_code,
    a.nic_description

FROM {{ ref('silver_msme_activities') }} a
LEFT JOIN {{ ref('dim_nic_code') }} n ON n.nic_code = a.nic_code
