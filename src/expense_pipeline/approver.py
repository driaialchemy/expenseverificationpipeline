"""Stage 5: Approval and finalization."""

from .schemas import (
    Expense,
    ExpenseVerdict,
    ApprovedExpense,
    VerdictComparison,
)
from .gates import gate_approver, GateFailure


def approve_expenses(
    expenses: list[Expense],
    checker_verdicts: list[ExpenseVerdict],
    verifier_verdicts: list[ExpenseVerdict],
) -> tuple[list[ApprovedExpense], list[VerdictComparison]]:
    """
    Split expenses into approved/flagged/needs_human_review based on checker+verifier agreement.

    - Approved: both checker and verifier say "approved"
    - Flagged: both checker and verifier say "flagged" and agree on reasons
    - Needs human review: disagreement between checker and verifier
    """
    # Index verdicts by report_id for easy lookup
    checker_by_id = {v.report_id: v for v in checker_verdicts}
    verifier_by_id = {v.report_id: v for v in verifier_verdicts}

    approved_expenses = []
    disagreements = []

    for expense in expenses:
        checker_verdict = checker_by_id.get(expense.report_id)
        verifier_verdict = verifier_by_id.get(expense.report_id)

        if not checker_verdict or not verifier_verdict:
            raise ValueError(f"Missing verdict for {expense.report_id}")

        # Determine final status
        if checker_verdict.verdict == verifier_verdict.verdict == "approved":
            final_status = "approved"
        elif checker_verdict.verdict == verifier_verdict.verdict == "flagged":
            # Both flagged — check if reasons match
            checker_reasons_set = set(checker_verdict.reasons)
            verifier_reasons_set = set(verifier_verdict.reasons)
            if checker_reasons_set == verifier_reasons_set:
                final_status = "flagged"
            else:
                final_status = "needs_human_review"
                disagreements.append(
                    VerdictComparison(
                        report_id=expense.report_id,
                        checker_verdict=checker_verdict.verdict,
                        verifier_verdict=verifier_verdict.verdict,
                        match=False,
                    )
                )
        else:
            # Disagreement: one approved, one flagged
            final_status = "needs_human_review"
            disagreements.append(
                VerdictComparison(
                    report_id=expense.report_id,
                    checker_verdict=checker_verdict.verdict,
                    verifier_verdict=verifier_verdict.verdict,
                    match=False,
                )
            )

        approved_expenses.append(
            ApprovedExpense(
                expense=expense,
                checker_verdict=checker_verdict,
                verifier_verdict=verifier_verdict,
                final_status=final_status,
            )
        )

    # Gate: confirm all rows have been classified
    try:
        gate_approver(approved_expenses, len(expenses))
    except GateFailure as e:
        raise ValueError(f"Approver gate failed: {e}")

    return approved_expenses, disagreements
