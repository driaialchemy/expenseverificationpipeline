# Expense Verification Pipeline

A gated, multi-agent pipeline that verifies expense reports against company spending policy, loads results to Snowflake, and exposes a Streamlit dashboard for analysis.

## Overview

The pipeline consists of 6 stages:

1. **Ingestion** — Parse Excel expense spreadsheet
2. **Policy Parser** — Extract policy rules from Word document
3. **Compliance Checker** — LLM-assisted judgment on policy compliance
4. **Verifier** — Pure-code independent verification (no LLM)
5. **Approver** — Reconcile checker and verifier verdicts, finalize status
6. **Snowflake Loader** — Load verified results to Snowflake (optional)

Every stage is gated: gates check artifacts and re-computed values, never LLM output or status flags. The Snowflake load gate independently verifies the row count in the database.

## Installation

```bash
pip install -e .
pip install -e ".[dev]"  # for testing
```

## Setup

### 1. Configure Snowflake Credentials (optional)

Copy `.env.example` to `.env` and fill in your Snowflake details:

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required environment variables:
- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_PASSWORD` or `SNOWFLAKE_PRIVATE_KEY_PATH`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`
- `SNOWFLAKE_ROLE`
- `ANTHROPIC_API_KEY` (for LLM checker)

### 2. Create Snowflake Tables (if using Snowflake)

Run the DDL to create tables:

```bash
snowflake-connector-python
-- Then execute sql/001_create_tables.sql in your Snowflake account
```

## Usage

### Run the Pipeline

```bash
# Run without Snowflake (local reports only)
expense-verify run sample_expenses.xlsx sample_policy_manual.docx

# Run with Snowflake load
expense-verify run sample_expenses.xlsx sample_policy_manual.docx --load-to-snowflake
```

Output:
- `audit/` — JSON audit trail per run
- `reports/` — CSV reports of verdicts and summary

### Dashboard

#### Option 1: Native Streamlit in Snowflake (Recommended)

1. In Snowsight, navigate to **Streamlit apps**
2. Create new app and point to `dashboard/app.py`
3. Deploy and access

#### Option 2: Standalone Streamlit

```bash
streamlit run src/expense_pipeline/dashboard/app.py
```

The app auto-detects whether it's running in Streamlit-in-Snowflake (with Snowpark session) or standalone (using snowflake_conn.py).

## Architecture

### Data Flow

```
sample_expenses.xlsx
    ↓
[Stage 1: Ingestion] → expenseSheet
    ↓
sample_policy_manual.docx
    ↓
[Stage 2: Policy Parser] → policy_rules.yaml
    ↓
[Stage 3: Checker (LLM)] → checker_verdicts
[Stage 4: Verifier (Pure Code)] → verifier_verdicts
    ↓
[Stage 5: Approver] → approved_expenses (approved/flagged/needs_review)
    ↓
[Stage 6: Snowflake Loader] → EXPENSE_VERDICTS + RUN_SUMMARY (optional)
```

### Gates

Each stage is protected by a gate that verifies:

- **Stage 1**: File re-opened and row count matches
- **Stage 2**: Every expense category has a policy rule
- **Stage 3**: Row count parity and every row has a verdict
- **Stage 4**: Row count parity and every row has a verdict
- **Stage 5**: All rows classified (approved/flagged/needs_review)
- **Stage 6**: Independent Snowflake query confirms row count matches

## Testing

Run all tests:

```bash
pytest tests/
```

Run specific test file:

```bash
pytest tests/test_ingestion.py -v
```

Coverage:

```bash
pytest --cov=src/expense_pipeline tests/
```

## Project Structure

```
expense-verification-pipeline/
├── sample_expenses.xlsx              # Input spreadsheet
├── sample_policy_manual.docx         # Input policy document
├── src/expense_pipeline/
│   ├── __init__.py
│   ├── cli.py                        # CLI entry point
│   ├── schemas.py                    # Data models
│   ├── ingestion.py                  # Stage 1
│   ├── policy_parser.py              # Stage 2
│   ├── checker.py                    # Stage 3 (LLM)
│   ├── verifier.py                   # Stage 4 (Pure code)
│   ├── approver.py                   # Stage 5
│   ├── snowflake_loader.py           # Stage 6
│   ├── gates.py                      # Gate checks
│   ├── audit.py                      # Audit trail
│   ├── snowflake_conn.py             # Connection management
│   └── dashboard/
│       ├── __init__.py
│       ├── app.py                    # Streamlit app
│       └── queries.py                # SQL queries
├── sql/
│   └── 001_create_tables.sql        # Schema DDL
├── tests/                            # Test suite
├── audit/                            # Audit JSON (gitignored)
├── reports/                          # CSV reports (gitignored)
├── pyproject.toml
├── .gitignore
├── .env.example
├── README.md
└── CLAUDE.md
```

## Key Principles

1. **Gates check artifacts, not status flags** — Every decision point verifies actual data, not LLM output or function return values
2. **Independent verification** — Stage 4 verifier is pure code that re-derives verdicts without reading the checker
3. **Additive Snowflake writes** — Inserts are tagged by `run_id` and never destructive
4. **No secrets in git** — `.env` is gitignored; `.env.example` has placeholders only
5. **Comprehensive audit trail** — Every stage and gate check is logged to JSON

## API Keys and Credentials

- Anthropic API key is required for the LLM-assisted checker
- Snowflake credentials are optional (pipeline works offline without them)
- All credentials must come from environment variables, never hardcoded

## License

Internal use only.
