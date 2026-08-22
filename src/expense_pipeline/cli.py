"""Command-line interface for the expense verification pipeline."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from .ingestion import ingest_expenses
from .policy_parser import parse_policy_manual
from .checker import check_compliance
from .verifier import verify_compliance
from .approver import approve_expenses
from .snowflake_loader import load_to_snowflake
from .audit import (
    create_audit_file,
    log_stage_completion,
    log_gate_check,
    log_disagreement,
    log_snowflake_load,
    log_run_summary,
)
from .schemas import RunResult


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Expense verification pipeline against company spending policy"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the verification pipeline")
    run_parser.add_argument("spreadsheet", help="Path to expense spreadsheet (XLSX)")
    run_parser.add_argument("policy", help="Path to policy manual (DOCX)")
    run_parser.add_argument(
        "--load-to-snowflake",
        action="store_true",
        help="Load results to Snowflake (requires credentials)",
    )
    run_parser.add_argument(
        "--policy-yaml",
        default="src/expense_pipeline/data/policy_rules.yaml",
        help="Path to save parsed policy rules YAML",
    )
    run_parser.add_argument(
        "--audit-dir",
        default="audit",
        help="Directory for audit JSON files",
    )
    run_parser.add_argument(
        "--reports-dir",
        default="reports",
        help="Directory for report CSV files",
    )
    run_parser.set_defaults(func=run_pipeline)

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def run_pipeline(args):
    """Run the full verification pipeline."""
    run_id = str(uuid.uuid4())[:8]
    print(f"Starting expense verification run: {run_id}")

    # Setup audit trail
    audit_file = create_audit_file(args.audit_dir, run_id)
    report_dir = Path(args.reports_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Stage 1: Ingest expenses
        print("Stage 1: Ingesting expenses...")
        expense_sheet = ingest_expenses(args.spreadsheet)
        log_stage_completion(
            audit_file,
            "ingestion",
            "success",
            {"rows": len(expense_sheet.expenses)},
        )
        print(f"  [OK] Loaded {len(expense_sheet.expenses)} expenses")

        # Stage 2: Parse policy
        print("Stage 2: Parsing policy manual...")
        policy_rules = parse_policy_manual(args.policy, args.policy_yaml)
        log_stage_completion(
            audit_file,
            "policy_parser",
            "success",
            {"categories": len(policy_rules.rules)},
        )
        print(f"  [OK] Parsed {len(policy_rules.rules)} policy categories")

        # Stage 3: LLM-assisted checking
        print("Stage 3: Running compliance checks...")
        checker_output = check_compliance(expense_sheet.expenses, policy_rules)
        log_stage_completion(
            audit_file,
            "checker",
            "success",
            {
                "verdicts": len(checker_output.verdicts),
                "flagged": sum(1 for v in checker_output.verdicts if v.verdict == "flagged"),
            },
        )
        print(f"  [OK] Generated {len(checker_output.verdicts)} verdicts")

        # Stage 4: Independent verification
        print("Stage 4: Running independent verification...")
        verifier_output = verify_compliance(expense_sheet.expenses, policy_rules)
        log_stage_completion(
            audit_file,
            "verifier",
            "success",
            {
                "verdicts": len(verifier_output.verdicts),
                "flagged": sum(1 for v in verifier_output.verdicts if v.verdict == "flagged"),
            },
        )
        print(f"  [OK] Verified {len(verifier_output.verdicts)} verdicts")

        # Stage 5: Approval and finalization
        print("Stage 5: Finalizing approvals...")
        approved_expenses, disagreements = approve_expenses(
            expense_sheet.expenses,
            checker_output.verdicts,
            verifier_output.verdicts,
        )

        for disagreement in disagreements:
            log_disagreement(
                audit_file,
                disagreement.report_id,
                disagreement.checker_verdict,
                disagreement.verifier_verdict,
            )

        log_stage_completion(
            audit_file,
            "approver",
            "success",
            {
                "approved": sum(1 for e in approved_expenses if e.final_status == "approved"),
                "flagged": sum(1 for e in approved_expenses if e.final_status == "flagged"),
                "needs_review": sum(
                    1 for e in approved_expenses if e.final_status == "needs_human_review"
                ),
                "disagreements": len(disagreements),
            },
        )
        print(f"  [OK] Approved {sum(1 for e in approved_expenses if e.final_status == 'approved')} expenses")
        print(f"  [OK] Flagged {sum(1 for e in approved_expenses if e.final_status == 'flagged')} expenses")
        print(
            f"  [OK] {sum(1 for e in approved_expenses if e.final_status == 'needs_human_review')} need human review"
        )

        # Create run result
        run_result = RunResult(
            run_id=run_id,
            run_timestamp=datetime.utcnow(),
            expenses=expense_sheet.expenses,
            approved_expenses=approved_expenses,
            approved_count=sum(1 for e in approved_expenses if e.final_status == "approved"),
            flagged_count=sum(1 for e in approved_expenses if e.final_status == "flagged"),
            needs_review_count=sum(
                1 for e in approved_expenses if e.final_status == "needs_human_review"
            ),
            disagreements=disagreements,
        )

        # Stage 6: Optional Snowflake load
        if args.load_to_snowflake:
            print("Stage 6: Loading to Snowflake...")
            try:
                rows_loaded, verified_count = load_to_snowflake(run_id, approved_expenses)
                log_snowflake_load(
                    audit_file,
                    rows_loaded,
                    verified_count,
                    rows_loaded == verified_count,
                )
                print(f"  [OK] Loaded {rows_loaded} rows to Snowflake (verified: {verified_count})")
            except Exception as e:
                log_snowflake_load(audit_file, 0, 0, False)
                print(f"  [ERROR] Snowflake load failed: {e}", file=sys.stderr)
                raise
        else:
            print("Stage 6: Skipped (use --load-to-snowflake to enable)")

        # Write report CSVs
        print("Writing reports...")
        _write_reports(report_dir, run_result)

        log_run_summary(audit_file, run_result)

        print(f"\n[OK] Pipeline complete: {run_id}")
        print(f"  Audit trail: {audit_file}")
        print(f"  Reports: {report_dir}")

    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}", file=sys.stderr)
        raise


def _write_reports(report_dir: Path, run_result: RunResult) -> None:
    """Write CSV report files."""
    import csv

    # Verdicts report
    verdicts_file = report_dir / f"{run_result.run_id}_verdicts.csv"
    with open(verdicts_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "report_id",
                "employee",
                "department",
                "category",
                "amount",
                "receipt",
                "checker_verdict",
                "verifier_verdict",
                "final_status",
            ]
        )
        for approved_exp in run_result.approved_expenses:
            writer.writerow(
                [
                    approved_exp.expense.report_id,
                    approved_exp.expense.employee,
                    approved_exp.expense.department,
                    approved_exp.expense.category,
                    approved_exp.expense.amount,
                    "yes" if approved_exp.expense.receipt_attached else "no",
                    approved_exp.checker_verdict.verdict,
                    approved_exp.verifier_verdict.verdict,
                    approved_exp.final_status,
                ]
            )

    # Summary report
    summary_file = report_dir / f"{run_result.run_id}_summary.csv"
    with open(summary_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["metric", "value"]
        )
        writer.writerow(["run_id", run_result.run_id])
        writer.writerow(["total_expenses", len(run_result.expenses)])
        writer.writerow(["approved", run_result.approved_count])
        writer.writerow(["flagged", run_result.flagged_count])
        writer.writerow(["needs_review", run_result.needs_review_count])
        writer.writerow(["disagreements", len(run_result.disagreements)])


if __name__ == "__main__":
    main()
