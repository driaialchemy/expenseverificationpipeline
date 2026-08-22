"""Stage 6: Loading verified results into Snowflake."""

from datetime import datetime
from typing import Optional

from .schemas import ApprovedExpense, RunSummary
from .gates import gate_snowflake_load_verified, GateFailure
from .snowflake_conn import get_snowflake_connection


def load_to_snowflake(
    run_id: str, approved_expenses: list[ApprovedExpense]
) -> tuple[int, int]:
    """
    Load verified expenses and run summary to Snowflake.

    Returns: (rows_loaded, verified_count)

    Gate: independently verifies the load by querying Snowflake.
    Never trusts the loader's return value.
    """
    if not approved_expenses:
        raise ValueError("No expenses to load")

    conn = get_snowflake_connection()
    cursor = conn.cursor()

    try:
        # Insert expense verdicts
        insert_count = 0
        for approved_exp in approved_expenses:
            exp = approved_exp.expense
            checker_reasons = "|".join(approved_exp.checker_verdict.reasons)
            verifier_reasons = "|".join(approved_exp.verifier_verdict.reasons)

            cursor.execute(
                """
                INSERT INTO EXPENSE_VERDICTS (
                    run_id, report_id, employee, department, expense_date,
                    category, amount, currency, receipt_attached, notes,
                    checker_verdict, checker_reasons, verifier_verdict, verifier_reasons,
                    final_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    exp.report_id,
                    exp.employee,
                    exp.department,
                    exp.date,
                    exp.category,
                    exp.amount,
                    exp.currency,
                    exp.receipt_attached,
                    exp.notes,
                    approved_exp.checker_verdict.verdict,
                    checker_reasons,
                    approved_exp.verifier_verdict.verdict,
                    verifier_reasons,
                    approved_exp.final_status,
                ),
            )
            insert_count += 1

        # Count by final_status
        approved_count = sum(1 for e in approved_expenses if e.final_status == "approved")
        flagged_count = sum(1 for e in approved_expenses if e.final_status == "flagged")
        needs_review_count = sum(
            1 for e in approved_expenses if e.final_status == "needs_human_review"
        )

        # Insert run summary
        cursor.execute(
            """
            INSERT INTO RUN_SUMMARY (
                run_id, run_timestamp, rows_processed,
                approved_count, flagged_count, needs_review_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                datetime.utcnow(),
                len(approved_expenses),
                approved_count,
                flagged_count,
                needs_review_count,
            ),
        )

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise ValueError(f"Failed to load to Snowflake: {e}")
    finally:
        cursor.close()

    # Gate: independently verify the load count
    try:
        gate_snowflake_load_verified(conn, run_id, len(approved_expenses))
    except GateFailure as e:
        raise ValueError(f"Snowflake load gate failed: {e}")

    conn.close()

    return insert_count, len(approved_expenses)
