"""Inject credits (title, subtitle, composer) from facts, idempotently.

MusicXML wants `<credit>` before `<part-list>`; a credit already carrying the same type and text
is left alone, so the inject phase can run repeatedly.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class ApplyCreditsFacts:
    spec = PassSpec(
        name="apply_credits_facts",
        phase=Phase.INJECT,
        kind=Kind.MECHANICAL,
        owns=("credits",),
        description="insert title/composer credits from facts, never duplicating one",
        measure="credits not yet present in the score",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        credits = (ctx.facts or {}).get("credits") or []
        added = 0
        for credit in credits:
            text = (credit.get("text") or "").strip()
            credit_type = (credit.get("type") or "title").strip()
            if not text:
                continue
            if _already_present(doc, credit_type, text):
                continue
            element = ElementTree.Element("credit", {"page": str(credit.get("page") or 1)})
            ElementTree.SubElement(element, "credit-type").text = credit_type
            ElementTree.SubElement(element, "credit-words").text = text
            _insert(doc, element)
            added += 1
        return PassResult(changed=added)


def _already_present(doc: Document, credit_type: str, text: str) -> bool:
    for credit in doc.root.findall("credit"):
        if (credit.findtext("credit-type") or "") != credit_type:
            continue
        if (credit.findtext("credit-words") or "").strip() == text:
            return True
    return False


def _insert(doc: Document, element) -> None:
    children = list(doc.root)
    index = next(
        (position for position, child in enumerate(children) if child.tag == "part-list"),
        len(children),
    )
    doc.root.insert(index, element)


INJECT_CREDITS = ApplyCreditsFacts()
