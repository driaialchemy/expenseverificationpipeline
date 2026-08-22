"""Tests for gate checking logic."""

import pytest
import tempfile
from pathlib import Path

from src.expense_pipeline.schemas import (
    Expense,
    CheckerOutput,
    ExpenseVerdict,
    ApprovedExpense,
    PolicyRule,
    PolicyRules,
)
from src.expense_pipeline.gates import (
    gate_checker,
    gate_verifier,
    gate_approver,
    GateFailure,
)


def test_gate_checker_row_count_parity():
    """Test checker gate verifies row count parity."""
    expenses = [
        Expense(
            report_id="EXP-0001",
            employee="Alice",
            department="Engineering",
            date="2024-01-15",
            category="meals",
            amount=50.00,
            currency="USD",
            receipt_attached=True,
        ),
        Expense(
            report_id="EXP-0002",
            employee="Bob",
            department="Sales",
            date="2024-01-15",
            category="travel",
            amount=200.00,
            currency="USD",
            receipt_attached=True,
        ),
    ]

    # Valid output with matching row count
    verdicts = [
        ExpenseVerdict(
            report_id="EXP-0001",
            verdict="approved",
            reasons=[],
            rule_citations=[],
        ),
        ExpenseVerdict(
            report_id="EXP-0002",
            verdict="flagged",
            reasons=["exceeds daily limit"],
            rule_citations=["travel.daily_limit"],
        ),
    ]
    checker_output = CheckerOutput(verdicts=verdicts)

    # Should not raise
    gate_checker(expenses, checker_output)

    # Mismatched row count
    verdicts_short = [verdicts[0]]
    checker_output_short = CheckerOutput(verdicts=verdicts_short)

    with pytest.raises(GateFailure) as exc_info:
        gate_checker(expenses, checker_output_short)

    assert "Row count mismatch" in str(exc_info.value)


def test_gate_checker_missing_verdicts():
    """Test checker gate detects missing verdicts."""
    expenses = [
        Expense(
            report_id="EXP-0001",
            employee="Alice",
            department="Engineering",
            date="2024-01-15",
            category="meals",
            amount=50.00,
            currency="USD",
            receipt_attached=True,
        ),
        Expense(
            report_id="EXP-0002",
            employee="Bob",
            department="Sales",
            date="2024-01-15",
            category="travel",
            amount=200.00,
            currency="USD",
            receipt_attached=True,
        ),
    ]

    # Missing verdict for EXP-0002
    verdicts = [
        ExpenseVerdict(
            report_id="EXP-0001",
            verdict="approved",
            reasons=[],
            rule_citations=[],
        ),
    ]
    checker_output = CheckerOutput(verdicts=verdicts)

    with pytest.raises(GateFailure):
        gate_checker(expenses, checker_output)


def test_gate_verifier_row_count_parity():
    """Test verifier gate verifies row count parity."""
    expenses = [
        Expense(
            report_id="EXP-0001",
            employee="Alice",
            department="Engineering",
            date="2024-01-15",
            category="meals",
            amount=50.00,
            currency="USD",
            receipt_attached=True,
        ),
    ]

    from src.expense_pipeline.schemas import VerifierOutput

    verdicts = [
        ExpenseVerdict(
            report_id="EXP-0001",
            verdict="approved",
            reasons=[],
            rule_citations=[],
        ),
    ]
    verifier_output = VerifierOutput(verdicts=verdicts)

    # Should not raise
    gate_verifier(expenses, verifier_output)

    # Mismatched row count
    verdicts_empty = []
    verifier_output_empty = VerifierOutput(verdicts=verdicts_empty)

    with pytest.raises(GateFailure):
        gate_verifier(expenses, verifier_output_empty)


def test_gate_approver_counts_all_statuses():
    """Test approver gate verifies all rows are classified."""
    rule = PolicyRule(
        category="meals",
        daily_limit=75,
        receipt_required_above=30,
    )
    rules = {"meals": rule}
    policy_rules = PolicyRules(rules=rules, source_file="test.yaml")

    expenses = [
        Expense(
            report_id="EXP-0001",
            employee="Alice",
            department="Engineering",
            date="2024-01-15",
            category="meals",
            amount=50.00,
            currency="USD",
            receipt_attached=True,
        ),
        Expense(
            report_id="EXP-0002",
            employee="Bob",
            department="Sales",
            date="2024-01-15",
            category="meals",
            amount=100.00,
            currency="USD",
            receipt_attached=True,
        ),
    ]

    checker_verdict_1 = ExpenseVerdict(
        report_id="EXP-0001",
        verdict="approved",
        reasons=[],
        rule_citations=[],
    )
    verifier_verdict_1 = ExpenseVerdict(
        report_id="EXP-0001",
        verdict="approved",
        reasons=[],
        rule_citations=[],
    )

    checker_verdict_2 = ExpenseVerdict(
        report_id="EXP-0002",
        verdict="flagged",
        reasons=["exceeds daily limit"],
        rule_citations=["meals.daily_limit"],
    )
    verifier_verdict_2 = ExpenseVerdict(
        report_id="EXP-0002",
        verdict="flagged",
        reasons=["exceeds daily limit"],
        rule_citations=["meals.daily_limit"],
    )

    approved_expenses = [
        ApprovedExpense(
            expense=expenses[0],
            checker_verdict=checker_verdict_1,
            verifier_verdict=verifier_verdict_1,
            final_status="approved",
        ),
        ApprovedExpense(
            expense=expenses[1],
            checker_verdict=checker_verdict_2,
            verifier_verdict=verifier_verdict_2,
            final_status="flagged",
        ),
    ]

    # Should not raise
    gate_approver(approved_expenses, len(expenses))

    # Incomplete classification
    approved_expenses_incomplete = [approved_expenses[0]]

    with pytest.raises(GateFailure) as exc_info:
        gate_approver(approved_expenses_incomplete, len(expenses))

    assert "Row count mismatch" in str(exc_info.value)
