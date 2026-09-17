SELECT
    enterprise_key,
    country,
    msme,
    enterprise_name,
    communication_address,
    registration_date,
    state_code,
    state_name,
    district_code,
    district_name,
    pincode

FROM {{ ref('silver_msme') }}
