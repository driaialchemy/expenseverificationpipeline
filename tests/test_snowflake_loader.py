"""Tests for Stage 6: Snowflake Loader."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.expense_pipeline.schemas import (
    Expense,
    ExpenseVerdict,
    ApprovedExpense,
)
from src.expense_pipeline.gates import GateFailure, gate_snowflake_load_verified


def create_test_approved_expenses():
    """Create test approved expenses."""
    expense = Expense(
        report_id="EXP-0001",
        employee="Alice",
        department="Engineering",
        date="2024-01-15",
        category="meals",
        amount=50.00,
        currency="USD",
        receipt_attached=True,
    )

    checker_verdict = ExpenseVerdict(
        report_id="EXP-0001",
        verdict="approved",
        reasons=[],
        rule_citations=[],
    )

    verifier_verdict = ExpenseVerdict(
        report_id="EXP-0001",
        verdict="approved",
        reasons=[],
        rule_citations=[],
    )

    return [
        ApprovedExpense(
            expense=expense,
            checker_verdict=checker_verdict,
            verifier_verdict=verifier_verdict,
            final_status="approved",
        )
    ]


def test_gate_snowflake_load_verified_success():
    """Test successful Snowflake load verification."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (1,)  # One row inserted

    # Should not raise
    gate_snowflake_load_verified(mock_conn, "run-123", 1)

    mock_cursor.execute.assert_called_once()
    args, kwargs = mock_cursor.execute.call_args
    assert "run-123" in str(args) or "run-123" in str(kwargs)


def test_gate_snowflake_load_verified_mismatch():
    """Test Snowflake load verification with row count mismatch."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (0,)  # Zero rows (mismatch)

    with pytest.raises(GateFailure) as exc_info:
        gate_snowflake_load_verified(mock_conn, "run-123", 1)

    assert "Row count mismatch" in str(exc_info.value)


def test_gate_snowflake_load_verified_connection_error():
    """Test Snowflake load verification with connection error."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.execute.side_effect = Exception("Connection failed")

    with pytest.raises(GateFailure) as exc_info:
        gate_snowflake_load_verified(mock_conn, "run-123", 1)

    assert "Failed to verify" in str(exc_info.value)


@patch("src.expense_pipeline.snowflake_loader.get_snowflake_connection")
def test_load_to_snowflake_calls_gate(mock_get_conn):
    """Test that load_to_snowflake calls the verification gate."""
    from src.expense_pipeline.snowflake_loader import load_to_snowflake

    # Setup mock connection
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (1,)  # Gate returns 1 row
    mock_get_conn.return_value = mock_conn

    approved_expenses = create_test_approved_expenses()

    rows_loaded, verified_count = load_to_snowflake("run-123", approved_expenses)

    assert rows_loaded == 1
    assert verified_count == 1
    mock_cursor.execute.assert_called()


@patch("src.expense_pipeline.snowflake_loader.get_snowflake_connection")
def test_load_to_snowflake_gate_failure(mock_get_conn):
    """Test that load_to_snowflake fails when gate verification fails."""
    from src.expense_pipeline.snowflake_loader import load_to_snowflake

    # Setup mock connection that returns wrong count
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (0,)  # Wrong count
    mock_get_conn.return_value = mock_conn

    approved_expenses = create_test_approved_expenses()

    with pytest.raises(ValueError) as exc_info:
        load_to_snowflake("run-123", approved_expenses)

    assert "gate failed" in str(exc_info.value).lower()


@patch("src.expense_pipeline.snowflake_loader.get_snowflake_connection")
def test_load_to_snowflake_empty_expenses(mock_get_conn):
    """Test that load_to_snowflake fails with no expenses."""
    from src.expense_pipeline.snowflake_loader import load_to_snowflake

    with pytest.raises(ValueError) as exc_info:
        load_to_snowflake("run-123", [])

    assert "No expenses" in str(exc_info.value)
