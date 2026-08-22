"""Tests for Stage 1: Ingestion."""

import pytest
import tempfile
from pathlib import Path
import openpyxl

from src.expense_pipeline.ingestion import ingest_expenses
from src.expense_pipeline.gates import GateFailure


def create_test_spreadsheet(path: str, num_rows: int = 3):
    """Create a test expense spreadsheet."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "expenses"

    # Header row
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

    # Data rows
    for i in range(num_rows):
        ws.append([
            f"EXP-{i:04d}",
            f"Employee{i}",
            "Sales" if i % 2 == 0 else "Engineering",
            "2024-01-01",
            "meals" if i % 3 == 0 else "travel",
            50.00 + i,
            "USD",
            True if i % 2 == 0 else False,
            f"Note {i}",
        ])

    wb.save(path)


def test_ingest_expenses_valid():
    """Test ingesting a valid expense spreadsheet."""
    with tempfile.TemporaryDirectory() as tmpdir:
        spreadsheet_path = Path(tmpdir) / "expenses.xlsx"
        create_test_spreadsheet(str(spreadsheet_path), num_rows=3)

        sheet = ingest_expenses(str(spreadsheet_path))

        assert sheet.row_count == 3
        assert len(sheet.expenses) == 3
        assert sheet.expenses[0].report_id == "EXP-0000"
        assert sheet.expenses[0].employee == "Employee0"
        assert sheet.expenses[0].department == "Sales"
        assert sheet.expenses[0].amount == 50.00


def test_ingest_expenses_row_count_gate():
    """Test that ingestion gate verifies row count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        spreadsheet_path = Path(tmpdir) / "expenses.xlsx"
        create_test_spreadsheet(str(spreadsheet_path), num_rows=5)

        sheet = ingest_expenses(str(spreadsheet_path))
        assert sheet.row_count == 5


def test_ingest_expenses_file_not_found():
    """Test error when file doesn't exist."""
    with pytest.raises(FileNotFoundError):
        ingest_expenses("/nonexistent/path.xlsx")


def test_ingest_expenses_department_column():
    """Test that department column is properly ingested."""
    with tempfile.TemporaryDirectory() as tmpdir:
        spreadsheet_path = Path(tmpdir) / "expenses.xlsx"
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

        ws.append([
            "EXP-0001",
            "Alice",
            "Finance",
            "2024-01-01",
            "software",
            1000.00,
            "USD",
            True,
        ])

        wb.save(str(spreadsheet_path))

        sheet = ingest_expenses(str(spreadsheet_path))
        assert sheet.expenses[0].department == "Finance"
