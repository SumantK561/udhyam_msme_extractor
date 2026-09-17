CREATE STORAGE INTEGRATION UDYAM_S3_INT
    TYPE = EXTERNAL_STAGE
    STORAGE_PROVIDER = 'S3'
    ENABLED = TRUE
    STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::<account-id>:role/udyam-snowflake-role'
    STORAGE_ALLOWED_LOCATIONS = ('s3://supplier-udyam-raw/udyam/raw/');

-- Get the Snowflake-managed IAM principal — you need these two values next
DESC INTEGRATION UDYAM_S3_INT;
