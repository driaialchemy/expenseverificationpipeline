"""Stage 4: Pure-code independent verification (no LLM)."""

from .schemas import Expense, PolicyRules, ExpenseVerdict, VerifierOutput
from .gates import gate_verifier, GateFailure
from .policy_parser import normalize_category


def verify_compliance(
    expenses: list[Expense], policy_rules: PolicyRules
) -> VerifierOutput:
    """
    Pure code verification of expenses against policy rules.

    Does NOT read Checker output. Re-derives verdicts independently using only
    the raw spreadsheet and raw policy YAML.

    Gate confirms row-count parity and every row has a verdict.
    """
    verdicts = []

    for expense in expenses:
        verdict = _verify_single_expense(expense, policy_rules)
        verdicts.append(verdict)

    output = VerifierOutput(verdicts=verdicts)

    # Gate: confirm row count parity and all rows have verdicts
    try:
        gate_verifier(expenses, output)
    except GateFailure as e:
        raise ValueError(f"Verifier gate failed: {e}")

    return output


def _verify_single_expense(expense: Expense, policy_rules: PolicyRules) -> ExpenseVerdict:
    """Verify a single expense against policy rules."""
    reasons = []
    rule_citations = []

    category_lower = normalize_category(expense.category)
    rule = next(
        (
            candidate
            for name, candidate in policy_rules.rules.items()
            if normalize_category(name) == category_lower
        ),
        None,
    )
    if rule is None:
        reasons.append(f"Unknown category: {expense.category}")
        return ExpenseVerdict(
            report_id=expense.report_id,
            verdict="flagged",
            reasons=reasons,
            rule_citations=rule_citations,
        )

    # Check daily limit
    if expense.amount > rule.daily_limit:
        reasons.append(f"Exceeds daily limit of ${rule.daily_limit}")
        rule_citations.append(f"{category_lower}.daily_limit")

    # Check receipt requirement
    if (
        expense.amount > rule.receipt_required_above
        and not expense.receipt_attached
    ):
        reasons.append(
            f"Receipt required for amounts > ${rule.receipt_required_above}"
        )
        rule_citations.append(f"{category_lower}.receipt_required_above")

    # Check manager approval requirement
    if rule.requires_manager_approval_above:
        if expense.amount > rule.requires_manager_approval_above:
            reasons.append(
                f"Manager approval required for amounts > ${rule.requires_manager_approval_above}"
            )
            rule_citations.append(f"{category_lower}.requires_manager_approval_above")

    verdict = "approved" if not reasons else "flagged"

    return ExpenseVerdict(
        report_id=expense.report_id,
        verdict=verdict,
        reasons=reasons,
        rule_citations=rule_citations,
    )
