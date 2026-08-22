"""Tests for Stage 4: Verifier (pure code, no LLM)."""

import pytest

from src.expense_pipeline.schemas import Expense, PolicyRule, PolicyRules
from src.expense_pipeline.verifier import verify_compliance


def create_test_expenses():
    """Create test expense data."""
    return [
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
            receipt_attached=False,
        ),
        Expense(
            report_id="EXP-0003",
            employee="Carol",
            department="Finance",
            date="2024-01-15",
            category="software",
            amount=2000.00,
            currency="USD",
            receipt_attached=True,
        ),
    ]


def create_test_policy():
    """Create test policy rules."""
    rules = {
        "meals": PolicyRule(
            category="meals",
            daily_limit=75.00,
            receipt_required_above=30.00,
        ),
        "travel": PolicyRule(
            category="travel",
            daily_limit=500.00,
            receipt_required_above=150.00,
        ),
        "software": PolicyRule(
            category="software",
            daily_limit=1500.00,
            receipt_required_above=500.00,
            requires_manager_approval_above=750.00,
        ),
    }
    return PolicyRules(rules=rules, source_file="test.yaml")


def test_verify_compliance_approved_expense():
    """Test verification of an expense that should be approved."""
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
        )
    ]
    policy = create_test_policy()

    output = verify_compliance(expenses, policy)

    assert len(output.verdicts) == 1
    assert output.verdicts[0].report_id == "EXP-0001"
    assert output.verdicts[0].verdict == "approved"
    assert len(output.verdicts[0].reasons) == 0


def test_verify_compliance_exceeds_daily_limit():
    """Test verification of an expense exceeding daily limit."""
    expenses = [
        Expense(
            report_id="EXP-0002",
            employee="Bob",
            department="Sales",
            date="2024-01-15",
            category="meals",
            amount=100.00,
            currency="USD",
            receipt_attached=True,
        )
    ]
    policy = create_test_policy()

    output = verify_compliance(expenses, policy)

    assert len(output.verdicts) == 1
    assert output.verdicts[0].verdict == "flagged"
    assert "daily limit" in " ".join(output.verdicts[0].reasons).lower()


def test_verify_compliance_missing_receipt():
    """Test verification of an expense missing required receipt."""
    expenses = [
        Expense(
            report_id="EXP-0003",
            employee="Carol",
            department="Finance",
            date="2024-01-15",
            category="meals",
            amount=75.00,
            currency="USD",
            receipt_attached=False,
        )
    ]
    policy = create_test_policy()

    output = verify_compliance(expenses, policy)

    assert len(output.verdicts) == 1
    assert output.verdicts[0].verdict == "flagged"
    assert "receipt" in " ".join(output.verdicts[0].reasons).lower()


def test_verify_compliance_manager_approval_required():
    """Test verification of software expense requiring manager approval."""
    expenses = [
        Expense(
            report_id="EXP-0004",
            employee="Dave",
            department="Engineering",
            date="2024-01-15",
            category="software",
            amount=1000.00,
            currency="USD",
            receipt_attached=True,
        )
    ]
    policy = create_test_policy()

    output = verify_compliance(expenses, policy)

    assert len(output.verdicts) == 1
    assert output.verdicts[0].verdict == "flagged"
    assert "manager approval" in " ".join(output.verdicts[0].reasons).lower()


def test_verify_compliance_row_count_parity():
    """Test that verifier preserves row count."""
    expenses = create_test_expenses()
    policy = create_test_policy()

    output = verify_compliance(expenses, policy)

    assert len(output.verdicts) == len(expenses)


def test_verify_compliance_never_depends_on_checker():
    """Test that verifier is independent and doesn't read checker output."""
    # This test documents the design principle: verifier uses only raw data
    expenses = create_test_expenses()
    policy = create_test_policy()

    # Verifier should work with no checker output present
    output = verify_compliance(expenses, policy)

    assert len(output.verdicts) == len(expenses)
    assert output.stage == "verifier"
