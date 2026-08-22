-- Snowflake schema for expense verification pipeline

CREATE TABLE IF NOT EXISTS EXPENSE_VERDICTS (
  run_id STRING,
  report_id STRING,
  employee STRING,
  department STRING,
  expense_date DATE,
  category STRING,
  amount NUMBER(10, 2),
  currency STRING,
  receipt_attached BOOLEAN,
  notes STRING,
  checker_verdict STRING,
  checker_reasons STRING,
  verifier_verdict STRING,
  verifier_reasons STRING,
  final_status STRING,
  loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS RUN_SUMMARY (
  run_id STRING,
  run_timestamp TIMESTAMP_NTZ,
  rows_processed NUMBER,
  approved_count NUMBER,
  flagged_count NUMBER,
  needs_review_count NUMBER,
  loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
