{{
    config(
        unique_key        = 'enterprise_key',
        incremental_strategy = 'merge',
        on_schema_change  = 'sync_all_columns',
    )
}}

WITH bronze AS (

    SELECT * FROM {{ ref('bronze_msme') }}

    {% if is_incremental() %}
        WHERE ingested_at > (SELECT MAX(ingested_at) FROM {{ this }})
    {% endif %}

),

deduped AS (

    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY enterprise_name, state_code, district_code, registration_date
            ORDER BY ingested_at DESC
        ) AS _rn

    FROM bronze
    WHERE enterprise_name IS NOT NULL
      AND TRIM(enterprise_name) != ''
      -- must contain at least one letter; filters out digit-only, symbol-only,
      -- and whitespace-only names (e.g. ".", ",", "123", ".....", "   ")
      AND REGEXP_LIKE(TRIM(enterprise_name), '.*[A-Za-z].*')

)

SELECT
    MD5(
        COALESCE(TRIM(enterprise_name), '')  || '|' ||
        COALESCE(state_code::VARCHAR, '')    || '|' ||
        COALESCE(district_code::VARCHAR, '') || '|' ||
        COALESCE(registration_date::VARCHAR, '')
    )                                           AS enterprise_key,

    -- Geography
    'IND'                                       AS country,
    state_code,
    state_name,
    district_code,
    district_name,
    pincode,

    -- Enterprise
    1                                           AS msme,
    registration_date,
    TRIM(enterprise_name)                       AS enterprise_name,
    communication_address,
    activities,

    -- Lineage
    run_id,
    batch_id,
    source_file,
    source_offset,
    ingested_at,
    CURRENT_TIMESTAMP()                         AS silver_loaded_at

FROM deduped
WHERE _rn = 1
