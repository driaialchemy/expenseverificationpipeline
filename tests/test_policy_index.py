"""Tests for policy-manual page/paragraph citations."""

from pathlib import Path

from src.expense_pipeline.policy_index import load_policy_citations
from src.expense_pipeline.policy_parser import normalize_category
from src.expense_pipeline.schemas import Expense, PolicyRule, PolicyRules
from src.expense_pipeline.verifier import verify_compliance

SAMPLE_POLICY = Path("sample_policy_manual.docx")


def test_normalize_category_variants():
    assert normalize_category("Office Supplies") == "office_supplies"
    assert normalize_category("office_supplies") == "office_supplies"
    assert normalize_category("Client Entertainment") == "client_entertainment"


def test_load_policy_citations_from_sample_manual():
    if not SAMPLE_POLICY.exists():
        return
    citations = load_policy_citations(str(SAMPLE_POLICY))

    meals = citations["meals"]
    assert meals.section.startswith("5.1")
    assert meals.paragraph == 18
    assert meals.page == 1
    assert meals.excerpt.startswith("Meal expenses are reimbursable")
    assert meals.table_row == 1
    assert meals.table_excerpt and "75" in meals.table_excerpt

    travel = citations["travel"]
    assert travel.paragraph == 20
    assert travel.page == 2
    assert travel.excerpt.startswith("Travel expenses include")

    assert "software" in citations
    assert "office_supplies" in citations
    assert "client_entertainment" in citations


def test_verifier_matches_spaced_yaml_category():
    rules = PolicyRules(
        rules={
            "office supplies": PolicyRule(
                category="office supplies",
                daily_limit=150.0,
                receipt_required_above=25.0,
            )
        },
        source_file="test.yaml",
    )
    expenses = [
        Expense(
            report_id="EXP-0007",
            employee="Dana",
            department="Marketing",
            date="2024-01-15",
            category="office_supplies",
            amount=22.50,
            currency="USD",
            receipt_attached=True,
        )
    ]
    output = verify_compliance(expenses, rules)
    assert output.verdicts[0].verdict == "approved"
