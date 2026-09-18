{{
    config(
        unique_key        = 'activity_key',
        incremental_strategy = 'merge',
        on_schema_change  = 'sync_all_columns',
    )
}}

WITH silver AS (

    SELECT enterprise_key, activities, silver_loaded_at
    FROM {{ ref('silver_msme') }}

    {% if is_incremental() %}
        WHERE silver_loaded_at > (SELECT MAX(silver_loaded_at) FROM {{ this }})
    {% endif %}

),

flattened AS (

    SELECT
        s.enterprise_key,
        f.value:NIC5DigitId::VARCHAR    AS nic_code,
        f.value:Description::VARCHAR    AS nic_description

    FROM silver s,
    LATERAL FLATTEN(input => s.activities) f

    WHERE s.activities IS NOT NULL

),

deduped AS (

    SELECT
        enterprise_key,
        nic_code,
        nic_description
    FROM flattened
    WHERE nic_code IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY enterprise_key, nic_code
        ORDER BY nic_description
    ) = 1

)

SELECT
    MD5(enterprise_key || '|' || nic_code)  AS activity_key,
    enterprise_key,
    nic_code,
    nic_description,
    CURRENT_TIMESTAMP()                     AS silver_loaded_at

FROM deduped
