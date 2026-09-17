WITH base AS (

    SELECT DISTINCT
        country,
        state_code,
        state_name,
        district_code,
        district_name,
        pincode
    FROM {{ ref('silver_msme') }}

)

SELECT
    MD5(
        COALESCE(state_code::VARCHAR, '')    || '|' ||
        COALESCE(district_code::VARCHAR, '') || '|' ||
        COALESCE(pincode, '')
    )               AS geo_key,
    country,
    state_code,
    state_name,
    district_code,
    district_name,
    pincode

FROM base
