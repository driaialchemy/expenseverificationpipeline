"""Stage 2: Parsing of policy manual."""

import re
from pathlib import Path

import yaml
from docx import Document

from .schemas import PolicyRule, PolicyRules
from .gates import gate_policy_parser, GateFailure


def normalize_category(name: str) -> str:
    """Normalize category labels so 'Office Supplies' and office_supplies match."""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def parse_policy_manual(docx_path: str, output_yaml: str = None) -> PolicyRules:
    """
    Parse policy manual (DOCX) and extract category limits.

    Looks for Section 4 which contains the authoritative category-limits table.
    Writes to data/policy_rules.yaml if output_yaml path provided.
    """
    if not Path(docx_path).exists():
        raise FileNotFoundError(f"Policy manual not found: {docx_path}")

    doc = Document(docx_path)

    # Find Section 4 and extract the policy table
    rules_dict = {}
    section_4_found = False

    for para in doc.paragraphs:
        if "Section 4" in para.text or "section 4" in para.text.lower():
            section_4_found = True
        if section_4_found and para.text.strip().startswith(("meals", "travel")):
            rules_dict = _extract_rules_from_doc(doc)
            break

    if not rules_dict:
        rules_dict = _extract_rules_from_doc(doc)

    if not rules_dict:
        raise ValueError("Could not extract policy rules from document")

    rules = {}
    for category, rule_data in rules_dict.items():
        rules[category] = PolicyRule(
            category=category,
            daily_limit=float(rule_data.get("daily_limit", 0)),
            receipt_required_above=float(rule_data.get("receipt_required_above", 0)),
            requires_manager_approval_above=float(
                rule_data.get("requires_manager_approval_above")
            )
            if rule_data.get("requires_manager_approval_above")
            else None,
        )

    policy_rules = PolicyRules(rules=rules, source_file=docx_path)

    # Write YAML if output path provided
    if output_yaml:
        output_path = Path(output_yaml)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        yaml_data = {}
        for category, rule in rules.items():
            rule_dict = {
                "daily_limit": rule.daily_limit,
                "receipt_required_above": rule.receipt_required_above,
            }
            if rule.requires_manager_approval_above:
                rule_dict[
                    "requires_manager_approval_above"
                ] = rule.requires_manager_approval_above
            yaml_data[category] = rule_dict

        with open(output_path, "w") as f:
            yaml.dump(yaml_data, f, default_flow_style=False)

    return policy_rules


def _extract_rules_from_doc(doc: Document) -> dict:
    """Extract policy rules from tables in the document."""
    rules = {}

    for table in doc.tables:
        for row_idx, row in enumerate(table.rows):
            cells = row.cells
            if len(cells) >= 2:
                category = normalize_category(cells[0].text.strip())
                limit_text = cells[1].text.strip()

                # Skip header row and empty rows
                if not category or category in ("category", "limit", "daily limit"):
                    continue

                try:
                    # Extract numeric value from text like "$75 / day" or "75"
                    limit_value = float("".join(c for c in limit_text if c.isdigit() or c == "."))

                    receipt_text = cells[2].text.strip() if len(cells) > 2 else ""
                    receipt_value = float(
                        "".join(c for c in receipt_text if c.isdigit() or c == ".")
                    ) if receipt_text and any(c.isdigit() for c in receipt_text) else limit_value * 0.75

                    rule_data = {
                        "daily_limit": limit_value,
                        "receipt_required_above": receipt_value,
                    }

                    if category in ("software", "client_entertainment"):
                        approval_text = cells[3].text.strip() if len(cells) > 3 else ""
                        approval_value = float(
                            "".join(c for c in approval_text if c.isdigit() or c == ".")
                        ) if approval_text and any(c.isdigit() for c in approval_text) else limit_value * 0.5
                        rule_data["requires_manager_approval_above"] = approval_value

                    rules[category] = rule_data

                except (ValueError, IndexError):
                    continue

    return rules


def load_policy_rules_yaml(yaml_path: str) -> PolicyRules:
    """Load pre-parsed policy rules from YAML."""
    if not Path(yaml_path).exists():
        raise FileNotFoundError(f"Policy YAML not found: {yaml_path}")

    with open(yaml_path, "r") as f:
        yaml_data = yaml.safe_load(f)

    rules = {}
    for category, rule_data in yaml_data.items():
        category = normalize_category(category)
        rules[category] = PolicyRule(
            category=category,
            daily_limit=float(rule_data.get("daily_limit", 0)),
            receipt_required_above=float(rule_data.get("receipt_required_above", 0)),
            requires_manager_approval_above=float(
                rule_data.get("requires_manager_approval_above")
            )
            if rule_data.get("requires_manager_approval_above")
            else None,
        )

    return PolicyRules(rules=rules, source_file=yaml_path)
