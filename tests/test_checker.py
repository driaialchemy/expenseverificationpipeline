"""Tests for Stage 3: Compliance Checker (LLM-assisted)."""

import pytest
import json
from unittest.mock import Mock, patch

from src.expense_pipeline.schemas import Expense, PolicyRule, PolicyRules
from src.expense_pipeline.checker import check_compliance


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
    }
    return PolicyRules(rules=rules, source_file="test.yaml")


@patch("src.expense_pipeline.checker.Anthropic")
def test_check_compliance_basic(mock_anthropic_class):
    """Test basic compliance checking with mocked LLM."""
    expenses = create_test_expenses()
    policy = create_test_policy()

    # Mock LLM response
    mock_response_data = [
        {
            "report_id": "EXP-0001",
            "verdict": "approved",
            "reasons": [],
            "rule_citations": [],
        },
        {
            "report_id": "EXP-0002",
            "verdict": "flagged",
            "reasons": ["missing receipt"],
            "rule_citations": ["meals.receipt_required_above"],
        },
    ]

    mock_client = Mock()
    mock_anthropic_class.return_value = mock_client

    mock_message = Mock()
    mock_message.content = [Mock(text=json.dumps(mock_response_data))]
    mock_client.messages.create.return_value = mock_message

    output = check_compliance(expenses, policy)

    assert len(output.verdicts) == 2
    assert output.verdicts[0].report_id == "EXP-0001"
    assert output.verdicts[0].verdict == "approved"
    assert output.verdicts[1].verdict == "flagged"


@patch("src.expense_pipeline.checker.Anthropic")
def test_check_compliance_row_count_parity(mock_anthropic_class):
    """Test that checker preserves row count."""
    expenses = create_test_expenses()
    policy = create_test_policy()

    mock_response_data = [
        {
            "report_id": "EXP-0001",
            "verdict": "approved",
            "reasons": [],
            "rule_citations": [],
        },
        {
            "report_id": "EXP-0002",
            "verdict": "approved",
            "reasons": [],
            "rule_citations": [],
        },
    ]

    mock_client = Mock()
    mock_anthropic_class.return_value = mock_client

    mock_message = Mock()
    mock_message.content = [Mock(text=json.dumps(mock_response_data))]
    mock_client.messages.create.return_value = mock_message

    output = check_compliance(expenses, policy)

    assert len(output.verdicts) == len(expenses)


@patch("src.expense_pipeline.checker.Anthropic")
def test_check_compliance_missing_verdict(mock_anthropic_class):
    """Test gate failure when LLM output is missing a verdict."""
    expenses = create_test_expenses()
    policy = create_test_policy()

    # Missing verdict for second expense
    mock_response_data = [
        {
            "report_id": "EXP-0001",
            "verdict": "approved",
            "reasons": [],
            "rule_citations": [],
        },
    ]

    mock_client = Mock()
    mock_anthropic_class.return_value = mock_client

    mock_message = Mock()
    mock_message.content = [Mock(text=json.dumps(mock_response_data))]
    mock_client.messages.create.return_value = mock_message

    with pytest.raises(ValueError) as exc_info:
        check_compliance(expenses, policy)

    assert "gate failed" in str(exc_info.value).lower()


@patch("src.expense_pipeline.checker.Anthropic")
def test_check_compliance_invalid_json(mock_anthropic_class):
    """Test error handling for invalid JSON response from LLM."""
    expenses = create_test_expenses()
    policy = create_test_policy()

    mock_client = Mock()
    mock_anthropic_class.return_value = mock_client

    mock_message = Mock()
    mock_message.content = [Mock(text="This is not valid JSON")]
    mock_client.messages.create.return_value = mock_message

    with pytest.raises(ValueError) as exc_info:
        check_compliance(expenses, policy)

    assert "Failed to parse" in str(exc_info.value)
