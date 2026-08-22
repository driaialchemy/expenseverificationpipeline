"""Streamlit dashboard for expense verification results."""

import streamlit as st
import pandas as pd

from .queries import (
    get_run_ids,
    get_run_summary,
    get_expenses_for_run,
    get_department_breakdown,
    get_department_status_breakdown,
    get_category_breakdown,
    get_needs_review_expenses,
    get_unique_departments,
    get_unique_categories,
)
from ..snowflake_conn import get_snowflake_connection, get_snowpark_session


def get_connection():
    """Get Snowflake connection, preferring Snowpark session if available."""
    session = get_snowpark_session()
    if session:
        return session.connection
    else:
        return get_snowflake_connection()


def main():
    """Main dashboard app."""
    st.set_page_config(page_title="Expense Verification Dashboard", layout="wide")
    st.title("Expense Verification Dashboard")

    try:
        conn = get_connection()
    except Exception as e:
        st.error(f"Failed to connect to Snowflake: {e}")
        st.info("Make sure Snowflake credentials are configured in environment variables.")
        return

    # Get available runs
    try:
        run_ids = get_run_ids(conn)
    except Exception as e:
        st.error(f"Failed to load runs: {e}")
        return

    if not run_ids:
        st.warning("No runs found in database. Run the pipeline first.")
        return

    # Run selector
    selected_run_id = st.selectbox("Select a run:", run_ids)

    # Get run summary
    try:
        run_summary = get_run_summary(conn, selected_run_id)
    except Exception as e:
        st.error(f"Failed to load run summary: {e}")
        return

    if not run_summary:
        st.error("Run not found")
        return

    # Display run summary header
    st.subheader(f"Run: {selected_run_id}")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Processed", run_summary["rows_processed"])
    with col2:
        st.metric("Approved", run_summary["approved_count"])
    with col3:
        st.metric("Flagged", run_summary["flagged_count"])
    with col4:
        st.metric("Needs Review", run_summary["needs_review_count"])

    st.text(f"Run timestamp: {run_summary['run_timestamp']}")

    # Tabs for different views
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["Expenses", "Department Breakdown", "Category Breakdown", "Needs Review", "About"]
    )

    with tab1:
        st.subheader("Expense Details")
        _render_expenses_tab(conn, selected_run_id)

    with tab2:
        st.subheader("Department Breakdown")
        _render_department_tab(conn, selected_run_id)

    with tab3:
        st.subheader("Category Breakdown")
        _render_category_tab(conn, selected_run_id)

    with tab4:
        st.subheader("Expenses Requiring Human Review")
        _render_needs_review_tab(conn, selected_run_id)

    with tab5:
        st.subheader("About This Dashboard")
        st.markdown("""
        This dashboard displays results from the expense verification pipeline.
        The pipeline verifies expenses against company spending policy using both
        LLM-assisted compliance checking and independent pure-code verification.

        **Status meanings:**
        - **Approved**: Both checker and verifier agree the expense complies with policy
        - **Flagged**: Both checker and verifier agree the expense violates policy
        - **Needs Review**: Disagreement between checker and verifier, requires human judgment
        """)


def _render_expenses_tab(conn, run_id: str):
    """Render the expenses table with filters."""
    try:
        departments = get_unique_departments(conn, run_id)
        categories = get_unique_categories(conn, run_id)
    except Exception as e:
        st.error(f"Failed to load filter options: {e}")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        selected_department = st.selectbox(
            "Filter by Department",
            ["All"] + departments,
            key="dept_filter",
        )
    with col2:
        selected_category = st.selectbox(
            "Filter by Category",
            ["All"] + categories,
            key="cat_filter",
        )
    with col3:
        selected_status = st.selectbox(
            "Filter by Status",
            ["All", "approved", "flagged", "needs_human_review"],
            key="status_filter",
        )

    try:
        dept_filter = selected_department if selected_department != "All" else None
        cat_filter = selected_category if selected_category != "All" else None
        status_filter = selected_status if selected_status != "All" else None

        expenses = get_expenses_for_run(
            conn, run_id, dept_filter, cat_filter, status_filter
        )

        if not expenses:
            st.info("No expenses match the selected filters")
            return

        # Create DataFrame
        df = pd.DataFrame(expenses)
        df = df[
            [
                "report_id",
                "employee",
                "department",
                "category",
                "amount",
                "expense_date",
                "receipt_attached",
                "final_status",
            ]
        ]
        df["receipt_attached"] = df["receipt_attached"].map({True: "Yes", False: "No"})
        df = df.rename(
            columns={
                "report_id": "Report ID",
                "employee": "Employee",
                "department": "Department",
                "category": "Category",
                "amount": "Amount",
                "expense_date": "Date",
                "receipt_attached": "Receipt",
                "final_status": "Status",
            }
        )

        st.dataframe(df, use_container_width=True, hide_index=True)

        # Show summary
        st.text(f"Total: ${df['Amount'].sum():.2f} across {len(df)} expenses")

    except Exception as e:
        st.error(f"Failed to load expenses: {e}")


def _render_department_tab(conn, run_id: str):
    """Render department breakdown charts."""
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Total Reimbursed by Department")
        try:
            dept_data = get_department_breakdown(conn, run_id)
            if dept_data:
                df = pd.DataFrame(dept_data)
                df.set_index("department", inplace=True)
                st.bar_chart(df)
            else:
                st.info("No data available")
        except Exception as e:
            st.error(f"Failed to load department breakdown: {e}")

    with col2:
        st.markdown("### Status Count by Department")
        try:
            dept_status = get_department_status_breakdown(conn, run_id)
            if dept_status:
                df = pd.DataFrame(dept_status)
                pivot_df = df.pivot(index="department", columns="status", values="count").fillna(0)
                st.bar_chart(pivot_df)
            else:
                st.info("No data available")
        except Exception as e:
            st.error(f"Failed to load department status breakdown: {e}")


def _render_category_tab(conn, run_id: str):
    """Render category breakdown chart."""
    st.markdown("### Total Spend by Category")
    try:
        cat_data = get_category_breakdown(conn, run_id)
        if cat_data:
            df = pd.DataFrame(cat_data)
            df.set_index("category", inplace=True)
            st.bar_chart(df[["total_amount"]])

            # Show category details as table
            st.markdown("### Category Details")
            detail_df = pd.DataFrame(cat_data)
            detail_df = detail_df.rename(
                columns={"category": "Category", "total_amount": "Total Amount", "count": "Count"}
            )
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
        else:
            st.info("No data available")
    except Exception as e:
        st.error(f"Failed to load category breakdown: {e}")


def _render_needs_review_tab(conn, run_id: str):
    """Render expenses needing human review."""
    try:
        needs_review = get_needs_review_expenses(conn, run_id)

        if not needs_review:
            st.success("No expenses require human review!")
            return

        st.warning(f"{len(needs_review)} expenses require human review")

        for idx, expense in enumerate(needs_review):
            with st.container(border=True):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Report ID", expense["report_id"])
                with col2:
                    st.metric("Employee", expense["employee"])
                with col3:
                    st.metric("Department", expense["department"])

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Category", expense["category"])
                with col2:
                    st.metric("Amount", f"${expense['amount']:.2f}")
                with col3:
                    st.metric("Receipt", "Yes" if expense["receipt_attached"] else "No")

                st.markdown("**Checker Verdict:** " + expense["checker_verdict"])
                if expense["checker_reasons"]:
                    st.write("Reasons: " + expense["checker_reasons"])

                st.markdown("**Verifier Verdict:** " + expense["verifier_verdict"])
                if expense["verifier_reasons"]:
                    st.write("Reasons: " + expense["verifier_reasons"])

    except Exception as e:
        st.error(f"Failed to load needs-review expenses: {e}")


if __name__ == "__main__":
    main()
