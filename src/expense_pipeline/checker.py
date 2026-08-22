"""Stage 3: LLM-assisted compliance checking."""

import json
from datetime import datetime

from anthropic import Anthropic

from .schemas import Expense, PolicyRules, ExpenseVerdict, CheckerOutput
from .gates import gate_checker, GateFailure


def check_compliance(
    expenses: list[Expense], policy_rules: PolicyRules
) -> CheckerOutput:
    """
    Use LLM to perform compliance judgment on ambiguous expense rows.

    Returns verdict for each expense based on policy rules.
    Gate confirms row-count parity and every row has a verdict.
    """
    client = Anthropic()

    policy_summary = _build_policy_summary(policy_rules)
    expenses_text = _build_expenses_text(expenses)

    system_prompt = f"""You are an expense compliance auditor. Review each expense against the company policy.

Company Policy:
{policy_summary}

Respond with a JSON array of verdicts. Each verdict should follow this schema:
{{
  "report_id": "EXP-XXXX",
  "verdict": "approved" or "flagged",
  "reasons": ["reason1", "reason2"],
  "rule_citations": ["policy.rule"]
}}

For each expense, check:
1. Amount does not exceed daily category limit
2. Receipt requirement met (if amount over threshold, receipt must be attached)
3. Manager approval requirement met (if software/client_entertainment over threshold, needs approval)

Be conservative: flag any ambiguous cases for human review in reasons."""

    expenses_prompt = f"""Please review these expenses for policy compliance:

{expenses_text}

Return a JSON array with one verdict per expense, in the same order."""

    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": expenses_prompt}],
    )

    response_text = response.content[0].text

    try:
        json_start = response_text.find("[")
        json_end = response_text.rfind("]") + 1
        json_str = response_text[json_start:json_end]
        verdicts_data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Failed to parse LLM response: {e}\n\nResponse: {response_text}")

    verdicts = []
    for verdict_data in verdicts_data:
        try:
            verdict = ExpenseVerdict(
                report_id=verdict_data["report_id"],
                verdict=verdict_data["verdict"],
                reasons=verdict_data.get("reasons", []),
                rule_citations=verdict_data.get("rule_citations", []),
            )
            verdicts.append(verdict)
        except KeyError as e:
            raise ValueError(f"Missing field in verdict: {e}")

    output = CheckerOutput(verdicts=verdicts)

    # Gate: confirm row count parity and all rows have verdicts
    try:
        gate_checker(expenses, output)
    except GateFailure as e:
        raise ValueError(f"Checker gate failed: {e}")

    return output


def _build_policy_summary(policy_rules: PolicyRules) -> str:
    """Build a text summary of policy rules for the LLM."""
    lines = []
    for category, rule in policy_rules.rules.items():
        lines.append(f"- {category.title()}: ${rule.daily_limit}/day limit")
        lines.append(f"  Receipt required if > ${rule.receipt_required_above}")
        if rule.requires_manager_approval_above:
            lines.append(
                f"  Manager approval required if > ${rule.requires_manager_approval_above}"
            )
    return "\n".join(lines)


def _build_expenses_text(expenses: list[Expense]) -> str:
    """Build a text representation of expenses for the LLM."""
    lines = []
    for exp in expenses:
        receipt_status = "attached" if exp.receipt_attached else "missing"
        lines.append(
            f"{exp.report_id}: {exp.employee} ({exp.department}) - "
            f"{exp.category.upper()} ${exp.amount} {exp.currency} on {exp.date} - "
            f"receipt {receipt_status}"
        )
        if exp.notes:
            lines.append(f"  Notes: {exp.notes}")
    return "\n".join(lines)
