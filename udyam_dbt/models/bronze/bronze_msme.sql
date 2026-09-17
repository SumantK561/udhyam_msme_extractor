{{
    config(
        unique_key = ['batch_id', 'source_offset'],
        incremental_strategy = 'merge',
        on_schema_change = 'sync_all_columns',
    )
}}

WITH source AS (

    SELECT * FROM {{ source('raw', 'msme') }}

    {% if is_incremental() %}
        WHERE _INGESTED_AT > (SELECT MAX(ingested_at) FROM {{ this }})
    {% endif %}

)

SELECT
    -- Geography
    TRY_CAST(LG_ST_CODE AS INTEGER)             AS state_code,
    TRIM(STATE)                                  AS state_name,
    TRY_CAST(LG_DT_CODE AS INTEGER)             AS district_code,
    TRIM(DISTRICT)                               AS district_name,
    LPAD(TRY_CAST(PINCODE AS FLOAT)::INTEGER::VARCHAR, 6, '0') AS pincode,

    -- Enterprise
    TRY_TO_DATE(REGISTRATION_DATE, 'DD/MM/YYYY') AS registration_date,
    TRIM(ENTERPRISE_NAME)                         AS enterprise_name,
    TRIM(COMMUNICATION_ADDRESS)                   AS communication_address,
    TRY_PARSE_JSON(ACTIVITIES)                    AS activities,

    -- Lineage
    _RUN_ID                                       AS run_id,
    _BATCH_ID                                     AS batch_id,
    _SOURCE_FILE                                  AS source_file,
    _SOURCE_OFFSET                                AS source_offset,
    _INGESTED_AT                                  AS ingested_at,
    CURRENT_TIMESTAMP()                           AS bronze_loaded_at

FROM source
