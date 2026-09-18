"""Stage 3: LLM-assisted compliance checking."""

import json
import os
import re
from datetime import datetime
from typing import Optional

import httpx
from anthropic import Anthropic

from .schemas import Expense, PolicyRules, ExpenseVerdict, CheckerOutput
from .gates import gate_checker, GateFailure


class AnthropicConnectionError(ValueError):
    """Raised when the Anthropic API cannot be reached."""


# Current Claude API IDs as of 2026. Older dated snapshots (e.g.
# claude-3-5-sonnet-20241022, claude-opus-4-1) return 404.
DEFAULT_MODEL = "claude-sonnet-5"
PREFERRED_MODEL_PREFIXES = (
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-5",
    "claude-sonnet",
    "claude-haiku",
    "claude-opus",
)


_SECRET_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


def resolve_model(model: Optional[str] = None) -> str:
    """Resolve the Claude model ID from argument, env, or default."""
    if model:
        return model.strip()
    configured = os.environ.get("ANTHROPIC_MODEL")
    return configured.strip() if configured else DEFAULT_MODEL


def _env_api_key() -> Optional[str]:
    raw = os.environ.get("ANTHROPIC_API_KEY")
    if raw is None:
        return None
    key = raw.strip().strip('"').strip("'").strip()
    return key or None


def _build_client(**kwargs) -> Anthropic:
    api_key = _env_api_key()
    if api_key:
        kwargs["api_key"] = api_key
    return Anthropic(timeout=120.0, max_retries=2, **kwargs)


def _redact_secrets(text: str) -> str:
    return _SECRET_RE.sub("sk-ant-[REDACTED]", text)


def check_compliance(
    expenses: list[Expense],
    policy_rules: PolicyRules,
    model: Optional[str] = None,
) -> CheckerOutput:
    """
    Use LLM to perform compliance judgment on ambiguous expense rows.

    Returns verdict for each expense based on policy rules.
    Gate confirms row-count parity and every row has a verdict.
    """
    resolved_model = resolve_model(model)
    try:
        return _run_checker(_build_client(), expenses, policy_rules, resolved_model)
    except Exception as exc:
        if _is_illegal_api_key_header(exc):
            raise AnthropicConnectionError(_illegal_api_key_message()) from exc
        if _is_model_not_found(exc) or not _is_connection_error(exc):
            raise
        print("  [WARN] Default network path failed; retrying over IPv4...")
        ipv4_client = _build_client(
            http_client=httpx.Client(
                timeout=120.0,
                transport=httpx.HTTPTransport(local_address="0.0.0.0"),
            ),
        )
        try:
            return _run_checker(ipv4_client, expenses, policy_rules, resolved_model)
        except Exception as retry_exc:
            if _is_connection_error(retry_exc):
                raise AnthropicConnectionError(_connection_error_message(retry_exc)) from retry_exc
            raise


def _run_checker(
    client: Anthropic,
    expenses: list[Expense],
    policy_rules: PolicyRules,
    model: str,
) -> CheckerOutput:
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


def _create_message(client: Anthropic, model: str, **kwargs):
    """Call Messages API, falling back to a model this API key can access."""
    try:
        return client.messages.create(model=model, **kwargs)
    except Exception as exc:
        if not _is_model_not_found(exc):
            raise
        available = _list_available_models(client)
        fallback = _pick_available_model(available, exclude=model)
        if fallback:
            print(f"  [WARN] Model '{model}' is not available; using '{fallback}'")
            return client.messages.create(model=fallback, **kwargs)
        raise ValueError(_model_not_found_message(model, available)) from exc


def _is_model_not_found(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    text = str(exc).lower()
    return "not_found_error" in text or ("404" in text and "model" in text)


def _is_connection_error(exc: Exception) -> bool:
    current: Optional[BaseException] = exc
    while current is not None:
        name = type(current).__name__
        if name in {"APIConnectionError", "APITimeoutError", "ConnectError", "ConnectTimeout"}:
            return True
        text = str(current).lower()
        if text.strip() in {"connection error.", "connection error"}:
            return True
        current = current.__cause__ or current.__context__
    return False


def _exception_chain(exc: BaseException) -> str:
    parts: list[str] = []
    current: Optional[BaseException] = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip() or type(current).__name__
        parts.append(f"{type(current).__name__}: {text}")
        current = current.__cause__ or current.__context__
    return _redact_secrets(" | ".join(parts))


def _is_illegal_api_key_header(exc: Exception) -> bool:
    current: Optional[BaseException] = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if "illegal header value" in str(current).lower():
            return True
        current = current.__cause__ or current.__context__
    return False


def _illegal_api_key_message() -> str:
    return (
        "ANTHROPIC_API_KEY has leading/trailing whitespace or quotes, which HTTP rejects. "
        "Remove spaces and quotes around the key in .env or your shell, then re-run."
    )


def _connection_error_message(exc: Exception) -> str:
    return (
        "Anthropic connection failed. "
        f"Underlying error: {_exception_chain(exc)}. "
        "Check outbound HTTPS to api.anthropic.com, proxy settings "
        "(HTTPS_PROXY), and corporate SSL inspection. "
        "Re-run with --skip-checker to finish using the independent verifier only."
    )


def _list_available_models(client: Anthropic) -> list[str]:
    try:
        page = client.models.list()
        return [item.id for item in getattr(page, "data", []) if getattr(item, "id", None)]
    except Exception:
        return []


def _pick_available_model(available: list[str], exclude: str) -> Optional[str]:
    remaining = [mid for mid in available if mid != exclude]
    for prefix in PREFERRED_MODEL_PREFIXES:
        for mid in remaining:
            if mid == prefix or mid.startswith(prefix):
                return mid
    return remaining[0] if remaining else None


def _model_not_found_message(model: str, available: list[str]) -> str:
    available_text = ", ".join(available) if available else "(could not list models for this key)"
    return (
        f"Anthropic model '{model}' is not available for this API key (404). "
        f"Set ANTHROPIC_MODEL or pass --model to a model your key can access. "
        f"Current IDs include claude-sonnet-5, claude-haiku-4-5, claude-opus-5. "
        f"Available to this key: {available_text}"
    )


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
