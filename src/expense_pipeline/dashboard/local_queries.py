"""Load dashboard data from local reports/*.csv when Snowflake is unavailable."""

from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]


def _reports_dir() -> Path:
    cwd_reports = Path.cwd() / "reports"
    if cwd_reports.exists():
        return cwd_reports
    return REPO_ROOT / "reports"


def _verdicts_path(run_id: str) -> Path:
    return _reports_dir() / f"{run_id}_verdicts.csv"


def _summary_path(run_id: str) -> Path:
    return _reports_dir() / f"{run_id}_summary.csv"


def _load_verdicts(run_id: str) -> pd.DataFrame:
    path = _verdicts_path(run_id)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "receipt" in df.columns and "receipt_attached" not in df.columns:
        df["receipt_attached"] = df["receipt"].astype(str).str.lower().isin({"yes", "true", "1"})
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df


def get_run_ids(_conn=None) -> list[str]:
    files = sorted(
        _reports_dir().glob("*_summary.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [path.name.removesuffix("_summary.csv") for path in files]


def get_run_summary(_conn, run_id: str) -> dict | None:
    path = _summary_path(run_id)
    if not path.exists():
        return None
    rows = pd.read_csv(path)
    metrics = {str(row.metric): row.value for row in rows.itertuples(index=False)}
    return {
        "run_id": str(metrics.get("run_id", run_id)),
        "run_timestamp": datetime.fromtimestamp(path.stat().st_mtime),
        "rows_processed": int(metrics.get("total_expenses", 0)),
        "approved_count": int(metrics.get("approved", 0)),
        "flagged_count": int(metrics.get("flagged", 0)),
        "needs_review_count": int(metrics.get("needs_review", 0)),
        "loaded_at": None,
    }


def get_expenses_for_run(
    _conn,
    run_id: str,
    department_filter=None,
    category_filter=None,
    status_filter=None,
) -> list[dict]:
    df = _load_verdicts(run_id)
    if df.empty:
        return []
    if department_filter:
        df = df[df["department"] == department_filter]
    if category_filter:
        df = df[df["category"] == category_filter]
    if status_filter:
        df = df[df["final_status"] == status_filter]
    df = df.sort_values("amount", ascending=False)

    results = []
    for row in df.itertuples(index=False):
        results.append(
            {
                "report_id": row.report_id,
                "employee": row.employee,
                "department": row.department,
                "expense_date": getattr(row, "expense_date", None),
                "category": row.category,
                "amount": float(row.amount),
                "currency": getattr(row, "currency", "USD"),
                "receipt_attached": bool(row.receipt_attached),
                "final_status": row.final_status,
                "checker_verdict": row.checker_verdict,
                "verifier_verdict": row.verifier_verdict,
                "checker_reasons": getattr(row, "checker_reasons", "") or "",
                "verifier_reasons": getattr(row, "verifier_reasons", "") or "",
            }
        )
    return results


def get_department_breakdown(_conn, run_id: str) -> list[dict]:
    df = _load_verdicts(run_id)
    if df.empty:
        return []
    grouped = df.groupby("department", as_index=False)["amount"].sum().sort_values(
        "amount", ascending=False
    )
    return [
        {"department": row.department, "total_amount": float(row.amount)}
        for row in grouped.itertuples(index=False)
    ]


def get_department_status_breakdown(_conn, run_id: str) -> list[dict]:
    df = _load_verdicts(run_id)
    if df.empty:
        return []
    grouped = (
        df.groupby(["department", "final_status"]).size().reset_index(name="status_count")
    )
    return [
        {
            "department": row.department,
            "status": row.final_status,
            "count": int(row.status_count),
        }
        for row in grouped.itertuples(index=False)
    ]


def get_category_breakdown(_conn, run_id: str) -> list[dict]:
    df = _load_verdicts(run_id)
    if df.empty:
        return []
    grouped = (
        df.groupby("category", as_index=False)
        .agg(total_amount=("amount", "sum"), expense_count=("report_id", "count"))
        .sort_values("total_amount", ascending=False)
    )
    return [
        {
            "category": row.category,
            "total_amount": float(row.total_amount),
            "count": int(row.expense_count),
        }
        for row in grouped.itertuples(index=False)
    ]


def get_needs_review_expenses(_conn, run_id: str) -> list[dict]:
    return get_expenses_for_run(_conn, run_id, status_filter="needs_human_review")


def get_unique_departments(_conn, run_id: str) -> list[str]:
    df = _load_verdicts(run_id)
    if df.empty:
        return []
    return sorted(df["department"].dropna().astype(str).unique().tolist())


def get_unique_categories(_conn, run_id: str) -> list[str]:
    df = _load_verdicts(run_id)
    if df.empty:
        return []
    return sorted(df["category"].dropna().astype(str).unique().tolist())
