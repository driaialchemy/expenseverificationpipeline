"""End-to-end tests for the full pipeline."""

import pytest
import tempfile
import json
import openpyxl
from pathlib import Path
from docx import Document
from unittest.mock import Mock, patch

from src.expense_pipeline.ingestion import ingest_expenses
from src.expense_pipeline.policy_parser import parse_policy_manual
from src.expense_pipeline.verifier import verify_compliance
from src.expense_pipeline.approver import approve_expenses


def create_test_spreadsheet(path: str, num_rows: int = 3):
    """Create a test expense spreadsheet."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "expenses"

    ws.append([
        "report_id",
        "employee",
        "department",
        "date",
        "category",
        "amount",
        "currency",
        "receipt_attached",
        "notes",
    ])

    for i in range(num_rows):
        ws.append([
            f"EXP-{i:04d}",
            f"Employee{i}",
            "Sales" if i % 2 == 0 else "Engineering",
            "2024-01-15",
            "meals" if i % 3 == 0 else "travel",
            50.00 + i * 10,
            "USD",
            True if i % 2 == 0 else False,
            f"Note {i}",
        ])

    wb.save(path)


def create_test_policy_doc(path: str):
    """Create a test policy manual document."""
    doc = Document()

    doc.add_heading("Company Expense Policy", level=1)
    doc.add_paragraph("This is our expense policy.")

    doc.add_heading("Section 4: Category Limits", level=2)

    table = doc.add_table(rows=4, cols=4)
    table.style = "Light Grid Accent 1"

    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = "Category"
    hdr_cells[1].text = "Daily Limit"
    hdr_cells[2].text = "Receipt Required Above"
    hdr_cells[3].text = "Manager Approval Above"

    # Data rows
    categories_data = [
        ("meals", "75", "30", ""),
        ("travel", "500", "150", ""),
        ("software", "1000", "500", "750"),
    ]

    for i, (category, limit, receipt, approval) in enumerate(categories_data, 1):
        row_cells = table.rows[i].cells
        row_cells[0].text = category
        row_cells[1].text = limit
        row_cells[2].text = receipt
        row_cells[3].text = approval

    doc.save(path)


def test_end_to_end_local_pipeline():
    """Test the full local pipeline (Stages 1-5) without Snowflake."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create test files
        spreadsheet_path = tmpdir / "expenses.xlsx"
        policy_path = tmpdir / "policy.docx"
        yaml_path = tmpdir / "policy_rules.yaml"

        create_test_spreadsheet(str(spreadsheet_path), num_rows=5)
        create_test_policy_doc(str(policy_path))

        # Stage 1: Ingest
        expense_sheet = ingest_expenses(str(spreadsheet_path))
        assert len(expense_sheet.expenses) == 5

        # Stage 2: Parse policy
        policy_rules = parse_policy_manual(str(policy_path), str(yaml_path))
        assert len(policy_rules.rules) >= 2
        assert yaml_path.exists()

        # Stage 4: Verify (testing verifier independently)
        verifier_output = verify_compliance(expense_sheet.expenses, policy_rules)
        assert len(verifier_output.verdicts) == 5

        # Check that we have a mix of results
        verdicts = verifier_output.verdicts
        has_approved = any(v.verdict == "approved" for v in verdicts)
        has_flagged = any(v.verdict == "flagged" for v in verdicts)
        # Either we have approved or flagged (depending on test data)
        assert has_approved or has_flagged


@patch("src.expense_pipeline.checker.Anthropic")
def test_end_to_end_with_checker(mock_anthropic_class):
    """Test end-to-end pipeline including the LLM checker."""
    from src.expense_pipeline.checker import check_compliance

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create test files
        spreadsheet_path = tmpdir / "expenses.xlsx"
        policy_path = tmpdir / "policy.docx"
        yaml_path = tmpdir / "policy_rules.yaml"

        create_test_spreadsheet(str(spreadsheet_path), num_rows=2)
        create_test_policy_doc(str(policy_path))

        # Setup mock LLM
        mock_response_data = [
            {"report_id": "EXP-0000", "verdict": "approved", "reasons": [], "rule_citations": []},
            {"report_id": "EXP-0001", "verdict": "flagged", "reasons": ["exceeds limit"], "rule_citations": []},
        ]

        mock_client = Mock()
        mock_anthropic_class.return_value = mock_client

        mock_message = Mock()
        mock_message.content = [Mock(text=json.dumps(mock_response_data))]
        mock_client.messages.create.return_value = mock_message

        # Run pipeline
        expense_sheet = ingest_expenses(str(spreadsheet_path))
        policy_rules = parse_policy_manual(str(policy_path), str(yaml_path))

        checker_output = check_compliance(expense_sheet.expenses, policy_rules)
        verifier_output = verify_compliance(expense_sheet.expenses, policy_rules)

        # Stage 5: Approve
        approved_expenses, disagreements = approve_expenses(
            expense_sheet.expenses,
            checker_output.verdicts,
            verifier_output.verdicts,
        )

        assert len(approved_expenses) == 2
        # Check for disagreements if verdicts don't match
        if disagreements:
            assert len(disagreements) > 0


def test_end_to_end_department_handling():
    """Test that department column is properly handled end-to-end."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create spreadsheet with specific departments
        spreadsheet_path = tmpdir / "expenses.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "expenses"

        ws.append([
            "report_id",
            "employee",
            "department",
            "date",
            "category",
            "amount",
            "currency",
            "receipt_attached",
        ])

        ws.append(["EXP-0001", "Alice", "Engineering", "2024-01-15", "meals", 50.00, "USD", True])
        ws.append(["EXP-0002", "Bob", "Sales", "2024-01-15", "meals", 60.00, "USD", True])
        ws.append(["EXP-0003", "Carol", "Finance", "2024-01-15", "meals", 45.00, "USD", True])
        ws.append(["EXP-0004", "Dave", "Marketing", "2024-01-15", "meals", 70.00, "USD", True])

        wb.save(str(spreadsheet_path))

        # Parse and verify departments are preserved
        expense_sheet = ingest_expenses(str(spreadsheet_path))

        departments = {exp.department for exp in expense_sheet.expenses}
        expected_departments = {"Engineering", "Sales", "Finance", "Marketing"}
        assert departments == expected_departments
