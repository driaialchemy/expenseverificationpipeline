"""Index policy-manual locations (page, paragraph, excerpt) by category."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .policy_parser import normalize_category

_SECTION_HEADING = re.compile(r"^\s*(\d+\.\d+)\s+(.+)$")
_WORDS_PER_PAGE = 350
_EXCERPT_WORDS = 14


@dataclass
class PolicyCitation:
    category: str
    section: str
    page: int
    paragraph: int
    excerpt: str
    table_page: Optional[int] = None
    table_row: Optional[int] = None
    table_excerpt: Optional[str] = None


def load_policy_citations(docx_path: str) -> dict[str, PolicyCitation]:
    """Read a policy DOCX and return citations keyed by normalized category."""
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"Policy manual not found: {docx_path}")

    doc = Document(str(path))
    use_rendered_pages = _has_rendered_page_breaks(doc)
    citations: dict[str, PolicyCitation] = {}
    page = 1
    paragraph_no = 0
    words_seen = 0
    pending_heading: Optional[tuple[str, str, int, int]] = None

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            if use_rendered_pages and _has_page_break(block) and paragraph_no > 0:
                page += 1
            paragraph_no += 1
            words_seen += len(text.split())
            if not use_rendered_pages:
                page = 1 + words_seen // _WORDS_PER_PAGE

            heading = _SECTION_HEADING.match(text)
            if heading:
                section = f"{heading.group(1)} {heading.group(2).strip()}"
                pending_heading = (normalize_category(heading.group(2)), section, page, paragraph_no)
                continue

            if pending_heading:
                category, section, _heading_page, _heading_para = pending_heading
                existing = citations.get(category)
                citations[category] = PolicyCitation(
                    category=category,
                    section=section,
                    page=page,
                    paragraph=paragraph_no,
                    excerpt=_excerpt(text),
                    table_page=existing.table_page if existing else None,
                    table_row=existing.table_row if existing else None,
                    table_excerpt=existing.table_excerpt if existing else None,
                )
                pending_heading = None
            continue

        if isinstance(block, Table):
            for row_idx, row in enumerate(block.rows):
                cells = [cell.text.strip() for cell in row.cells]
                if not cells or not cells[0]:
                    continue
                category = normalize_category(cells[0])
                if category in {"category", "limit", "daily_limit"}:
                    continue
                table_excerpt = " · ".join(part for part in cells if part)
                existing = citations.get(category)
                if existing:
                    existing.table_page = page
                    existing.table_row = row_idx
                    existing.table_excerpt = table_excerpt
                else:
                    citations[category] = PolicyCitation(
                        category=category,
                        section=f"Section 4 table, row {row_idx}",
                        page=page,
                        paragraph=paragraph_no,
                        excerpt=_excerpt(table_excerpt),
                        table_page=page,
                        table_row=row_idx,
                        table_excerpt=table_excerpt,
                    )

    return citations


def find_policy_manual() -> Optional[Path]:
    """Locate the sample policy manual from cwd or the repo root."""
    repo_root = Path(__file__).resolve().parents[2]
    for candidate in (
        Path.cwd() / "sample_policy_manual.docx",
        repo_root / "sample_policy_manual.docx",
        Path(__file__).resolve().parents[3] / "sample_policy_manual.docx",
    ):
        if candidate.is_file():
            return candidate
    return None


def _iter_blocks(doc: Document):
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _has_rendered_page_breaks(doc: Document) -> bool:
    return bool(doc.element.body.findall(".//" + qn("w:lastRenderedPageBreak")))


def _has_page_break(paragraph: Paragraph) -> bool:
    element = paragraph._p
    if element.findall(".//" + qn("w:lastRenderedPageBreak")):
        return True
    for break_el in element.findall(".//" + qn("w:br")):
        if break_el.get(qn("w:type")) == "page":
            return True
    return False


def _excerpt(text: str, word_count: int = _EXCERPT_WORDS) -> str:
    words = text.split()
    if len(words) <= word_count:
        return text
    return " ".join(words[:word_count]) + "…"
