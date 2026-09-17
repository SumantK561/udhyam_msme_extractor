WITH silver AS (

    SELECT * FROM {{ ref('silver_msme') }}

),

geo AS (

    SELECT geo_key, state_code, district_code, pincode
    FROM {{ ref('dim_geography') }}

)

SELECT
    s.enterprise_key                            AS registration_key,
    s.enterprise_key,
    g.geo_key,
    s.country,
    s.msme,
    s.registration_date,
    s.run_id,
    s.batch_id,
    s.ingested_at

FROM silver s
LEFT JOIN geo g
    ON  g.state_code    = s.state_code
    AND g.district_code = s.district_code
    AND g.pincode       = s.pincode
