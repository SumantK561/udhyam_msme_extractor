WITH ranked AS (

    SELECT
        nic_code,
        nic_description,
        ROW_NUMBER() OVER (
            PARTITION BY nic_code
            ORDER BY silver_loaded_at DESC
        ) AS _rn

    FROM {{ ref('silver_msme_activities') }}

)

SELECT
    MD5(nic_code)   AS nic_key,
    nic_code,
    nic_description

FROM ranked
WHERE _rn = 1
