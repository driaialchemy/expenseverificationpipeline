"""SQL queries used by the Streamlit dashboard."""


def get_run_ids(conn) -> list[str]:
    """Get all available run IDs."""
    query = "SELECT DISTINCT run_id FROM RUN_SUMMARY ORDER BY run_timestamp DESC"
    cursor = conn.cursor()
    cursor.execute(query)
    return [row[0] for row in cursor.fetchall()]


def get_run_summary(conn, run_id: str) -> dict:
    """Get summary for a specific run."""
    query = """
    SELECT
      run_id,
      run_timestamp,
      rows_processed,
      approved_count,
      flagged_count,
      needs_review_count,
      loaded_at
    FROM RUN_SUMMARY
    WHERE run_id = %s
    """
    cursor = conn.cursor()
    cursor.execute(query, (run_id,))
    row = cursor.fetchone()
    if not row:
        return None

    return {
        "run_id": row[0],
        "run_timestamp": row[1],
        "rows_processed": row[2],
        "approved_count": row[3],
        "flagged_count": row[4],
        "needs_review_count": row[5],
        "loaded_at": row[6],
    }


def get_expenses_for_run(
    conn,
    run_id: str,
    department_filter=None,
    category_filter=None,
    status_filter=None,
) -> list[dict]:
    """Get all expenses for a run with optional filters."""
    query = """
    SELECT
      report_id,
      employee,
      department,
      expense_date,
      category,
      amount,
      currency,
      receipt_attached,
      final_status,
      checker_verdict,
      verifier_verdict,
      checker_reasons,
      verifier_reasons
    FROM EXPENSE_VERDICTS
    WHERE run_id = %s
    """

    params = [run_id]

    if department_filter:
        query += " AND department = %s"
        params.append(department_filter)

    if category_filter:
        query += " AND category = %s"
        params.append(category_filter)

    if status_filter:
        query += " AND final_status = %s"
        params.append(status_filter)

    query += " ORDER BY amount DESC"

    cursor = conn.cursor()
    cursor.execute(query, params)

    results = []
    for row in cursor.fetchall():
        results.append({
            "report_id": row[0],
            "employee": row[1],
            "department": row[2],
            "expense_date": row[3],
            "category": row[4],
            "amount": row[5],
            "currency": row[6],
            "receipt_attached": row[7],
            "final_status": row[8],
            "checker_verdict": row[9],
            "verifier_verdict": row[10],
            "checker_reasons": row[11],
            "verifier_reasons": row[12],
        })

    return results


def get_department_breakdown(conn, run_id: str) -> list[dict]:
    """Get total reimbursed amount by department."""
    query = """
    SELECT
      department,
      SUM(amount) as total_amount
    FROM EXPENSE_VERDICTS
    WHERE run_id = %s
    GROUP BY department
    ORDER BY total_amount DESC
    """
    cursor = conn.cursor()
    cursor.execute(query, (run_id,))

    results = []
    for row in cursor.fetchall():
        results.append({
            "department": row[0],
            "total_amount": row[1],
        })

    return results


def get_department_status_breakdown(conn, run_id: str) -> list[dict]:
    """Get count of approved/flagged/needs_review by department."""
    query = """
    SELECT
      department,
      final_status,
      COUNT(*) as count
    FROM EXPENSE_VERDICTS
    WHERE run_id = %s
    GROUP BY department, final_status
    ORDER BY department, final_status
    """
    cursor = conn.cursor()
    cursor.execute(query, (run_id,))

    results = []
    for row in cursor.fetchall():
        results.append({
            "department": row[0],
            "status": row[1],
            "count": row[2],
        })

    return results


def get_category_breakdown(conn, run_id: str) -> list[dict]:
    """Get total spend by category."""
    query = """
    SELECT
      category,
      SUM(amount) as total_amount,
      COUNT(*) as count
    FROM EXPENSE_VERDICTS
    WHERE run_id = %s
    GROUP BY category
    ORDER BY total_amount DESC
    """
    cursor = conn.cursor()
    cursor.execute(query, (run_id,))

    results = []
    for row in cursor.fetchall():
        results.append({
            "category": row[0],
            "total_amount": row[1],
            "count": row[2],
        })

    return results


def get_needs_review_expenses(conn, run_id: str) -> list[dict]:
    """Get expenses that need human review."""
    return get_expenses_for_run(conn, run_id, status_filter="needs_human_review")


def get_unique_departments(conn, run_id: str) -> list[str]:
    """Get unique departments in a run."""
    query = """
    SELECT DISTINCT department
    FROM EXPENSE_VERDICTS
    WHERE run_id = %s
    ORDER BY department
    """
    cursor = conn.cursor()
    cursor.execute(query, (run_id,))
    return [row[0] for row in cursor.fetchall()]


def get_unique_categories(conn, run_id: str) -> list[str]:
    """Get unique categories in a run."""
    query = """
    SELECT DISTINCT category
    FROM EXPENSE_VERDICTS
    WHERE run_id = %s
    ORDER BY category
    """
    cursor = conn.cursor()
    cursor.execute(query, (run_id,))
    return [row[0] for row in cursor.fetchall()]
