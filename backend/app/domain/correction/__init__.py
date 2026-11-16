"""Correction planner: findings → reviewable change proposals (pure, deterministic).

Only findings with a known, safe fix produce proposals. The planner never invents content: it
changes formatting, structure levels, numbering and ordering, using values taken from the rule
that failed or from the document's own dominant style.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.domain.adm.model import AdmDocument, Caption, Heading, Paragraph
from app.domain.changes import (
    AddPageNumbers,
    DeleteBlocks,
    FitShape,
    Operation,
    Proposal,
    ReplaceText,
    SetHeadingLevel,
    SetPageSetup,
    SetParaFmt,
    SetRunFmt,
    SetShapeFontMin,
    SortReferences,
)
from app.domain.inspection.checks._util import label_number
from app.domain.udse.properties import to_pt
from app.domain.udse.schema import Rule

ROMAN = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]


def to_roman(n: int) -> str:
    out = ""
    for v, s in ROMAN:
        while n >= v:
            out += s
            n -= v
    return out


@dataclass
class FindingRef:
    """The subset of a stored finding the planner needs."""

    id: str
    code: str
    node_ids: list[str] = field(default_factory=list)
    expected: Any = None
    actual: Any = None
    rule_id: str | None = None


@dataclass
class Planned:
    proposal: Proposal
    finding_ids: list[str]


def _snip(t: str, n: int = 90) -> str:
    t = " ".join(t.split())
    return t if len(t) <= n else t[: n - 1] + "…"


class Planner:
    def __init__(self, adm: AdmDocument, rules: dict[str, Rule] | None = None, family: str | None = None) -> None:
        self.adm = adm
        self.rules = rules or {}
        self.family = family
        self.out: list[Planned] = []
        self._seen: set[str] = set()

    def add(self, proposal: Proposal, finding_ids: list[str]) -> None:
        key = proposal.model_dump_json(include={"ops"})
        if key in self._seen:  # identical change already proposed: just link the finding
            for p in self.out:
                if p.proposal.model_dump_json(include={"ops"}) == key:
                    p.finding_ids.extend(finding_ids)
            return
        self._seen.add(key)
        self.out.append(Planned(proposal, finding_ids))

    # --- helpers ------------------------------------------------------------------------
    def _text(self, node_id: str) -> str:
        n = self.adm.node(node_id)
        return n.text if n is not None else ""

    def _captions(self, kind: str) -> list[Caption]:
        return [b for b in self.adm.body if isinstance(b, Caption) and b.target_kind == kind and b.number]

    def _renumber(self, kind: str, roman: bool, fids: list[str], rule_id: str | None) -> None:
        """Renumber captions 1, 2, 3… and update in-text references to match (“Figure 3” → “Figure 2”)."""
        ops: list[Operation] = []
        before_lines, after_lines = [], []
        mapping: dict[str, str] = {}
        for i, c in enumerate(self._captions(kind), start=1):
            want = to_roman(i) if roman else str(i)
            if c.number == want or c.number is None:
                continue
            mapping.setdefault(c.number, want)
            new = re.sub(rf"^(\s*{re.escape(c.label)}\s*){re.escape(c.number)}", rf"\g<1>{want}", c.text, count=1)
            if new != c.text:
                ops.append(ReplaceText(node_id=c.id, before=c.text, after=new))
                before_lines.append(_snip(c.text, 50))
                after_lines.append(_snip(new, 50))
        if not ops:
            return
        word = r"(?:Fig\.?|Figure)" if kind == "figure" else r"Table"
        pattern = re.compile(
            rf"\b({word}\s*)({'|'.join(re.escape(k) for k in sorted(mapping, key=len, reverse=True))})\b", re.IGNORECASE
        )
        for b in self.adm.body:
            if isinstance(b, Paragraph) and b.role != "reference_entry" and pattern.search(b.text):
                new_text = pattern.sub(lambda m: m.group(1) + mapping[m.group(2)], b.text)  # simultaneous, no chains
                if new_text != b.text:
                    ops.append(ReplaceText(node_id=b.id, before=b.text, after=new_text))
                    before_lines.append(_snip(b.text, 50))
                    after_lines.append(_snip(new_text, 50))
        self.add(
            Proposal(
                title=f"Renumber {kind} captions and their in-text references",
                rationale=f"{kind.capitalize()} numbers must run 1, 2, 3… and the text must refer to the right numbers.",
                ops=ops,
                risk="structural",
                before="\n".join(before_lines),
                after="\n".join(after_lines),
                finding_codes=[f"{kind}-numbering"],
                rule_id=rule_id,
                node_ids=[o.node_id for o in ops if isinstance(o, ReplaceText)],
            ),
            fids,
        )

    def _refs(self) -> list[Paragraph]:
        return [b for b in self.adm.body if isinstance(b, Paragraph) and b.role == "reference_entry" and b.text.strip()]

    def _sort_refs(self, order: str, fids: list[str], rule_id: str | None) -> None:
        refs = self._refs()
        if len(refs) < 2:
            return
        for existing in self.out:  # one ordering per list; the standard's rule wins over the generic check
            if any(isinstance(o, SortReferences) for o in existing.proposal.ops):
                existing.finding_ids.extend(fids)
                if rule_id is not None:
                    existing.proposal.ops = [SortReferences(node_ids=[r.id for r in refs], order=order)]
                    existing.proposal.title = f"Sort references ({order})"
                    existing.proposal.rule_id = rule_id
                return
        self.add(
            Proposal(
                title=f"Sort references ({order})",
                rationale="Reference lists must follow the order the style requires.",
                ops=[SortReferences(node_ids=[r.id for r in refs], order=order)],
                risk="structural",
                before="\n".join(_snip(r.text, 60) for r in refs[:6]),
                after="(sorted)",
                rule_id=rule_id,
                node_ids=[r.id for r in refs],
            ),
            fids,
        )

    # --- planning -----------------------------------------------------------------------
    def plan(self, findings: list[FindingRef]) -> list[Planned]:
        numbering_done: set[str] = set()
        for f in findings:
            rule = self.rules.get(f.rule_id or "") if f.rule_id else None
            if rule is not None:
                self._plan_rule(f, rule, numbering_done)
            else:
                self._plan_inspection(f, numbering_done)
        return self.out

    def _plan_inspection(self, f: FindingRef, numbering_done: set[str]) -> None:
        code, node = f.code, (f.node_ids[0] if f.node_ids else None)
        if code == "STRUCT.HEADING_LEVEL_SKIP" and node and isinstance(f.expected, int):
            self.add(
                Proposal(
                    title=f"Make “{_snip(self._text(node), 40)}” a level-{f.expected} heading",
                    rationale="Headings must not skip levels.",
                    ops=[SetHeadingLevel(node_id=node, level=f.expected)],
                    risk="structural",
                    before=f"Heading {f.actual}",
                    after=f"Heading {f.expected}",
                    node_ids=[node],
                    finding_codes=[code],
                ),
                [f.id],
            )
        elif code == "STRUCT.FAKE_HEADING" and node:
            prev = 1
            for b in self.adm.body:
                if b.id == node:
                    break
                if isinstance(b, Heading) and b.level > 0:
                    prev = b.level
            level = min(prev + 1, 3)
            self.add(
                Proposal(
                    title=f"Apply Heading {level} style to “{_snip(self._text(node), 40)}”",
                    rationale="Manual bold text is invisible to the outline and table of contents.",
                    ops=[SetHeadingLevel(node_id=node, level=level)],
                    risk="structural",
                    before="Body text (bold)",
                    after=f"Heading {level}",
                    node_ids=[node],
                    finding_codes=[code],
                ),
                [f.id],
            )
        elif code in ("FMT.FONT_INCONSISTENT", "FMT.HEADING_INCONSISTENT") and node and isinstance(f.expected, dict):
            fam, size = f.expected.get("font_family"), f.expected.get("size_pt")
            act = f.actual or {}
            self.add(
                Proposal(
                    title=f"Set font to {fam} {size:g} pt" if size else f"Set font to {fam}",
                    rationale="Match the document's dominant style.",
                    ops=[SetRunFmt(node_ids=[node], font_family=fam, size_pt=size)],
                    risk="formatting_only",
                    before=f"{act.get('font_family')} {act.get('size_pt')} pt",
                    after=f"{fam} {size} pt",
                    node_ids=[node],
                    finding_codes=[code],
                ),
                [f.id],
            )
        elif code == "FMT.SPACING_INCONSISTENT" and node and isinstance(f.expected, int | float):
            self.add(
                Proposal(
                    title=f"Set line spacing to {f.expected:g}",
                    rationale="Match the document's line spacing.",
                    ops=[SetParaFmt(node_ids=[node], line_spacing=float(f.expected))],
                    risk="formatting_only",
                    before=f"{f.actual}",
                    after=f"{f.expected:g}",
                    node_ids=[node],
                    finding_codes=[code],
                ),
                [f.id],
            )
        elif code == "FMT.ALIGNMENT_INCONSISTENT" and node and isinstance(f.expected, str):
            self.add(
                Proposal(
                    title=f"Align {f.expected}",
                    rationale="Match the document's alignment.",
                    ops=[SetParaFmt(node_ids=[node], alignment=f.expected)],
                    risk="formatting_only",
                    before=str(f.actual),
                    after=f.expected,
                    node_ids=[node],
                    finding_codes=[code],
                ),
                [f.id],
            )
        elif code == "LAYOUT.EMPTY_PARAGRAPHS" and f.node_ids:
            self.add(
                Proposal(
                    title=f"Remove {len(f.node_ids)} empty paragraphs",
                    rationale="Blank paragraphs used as spacing break layout.",
                    ops=[DeleteBlocks(node_ids=f.node_ids)],
                    risk="structural",
                    before=f"{len(f.node_ids)} empty lines",
                    after="(removed)",
                    node_ids=f.node_ids,
                    finding_codes=[code],
                ),
                [f.id],
            )
        elif code == "PAGE.MARGINS_INCONSISTENT":
            margins = [s.margins for s in self.adm.page_setups if s.margins]
            if margins:
                common = Counter((m.top, m.bottom, m.left, m.right) for m in margins).most_common(1)[0][0]
                if len({(m.top, m.bottom, m.left, m.right) for m in margins}) > 1:
                    t, bot, left, r = common
                    self.add(
                        Proposal(
                            title="Use the same margins in every section",
                            rationale="Sections should share one text block.",
                            ops=[SetPageSetup(margins_pt={"top": t, "bottom": bot, "left": left, "right": r})],
                            risk="formatting_only",
                            before=str(f.actual),
                            after=f"{t / 72:g}/{bot / 72:g}/{left / 72:g}/{r / 72:g} in",
                            finding_codes=[code],
                        ),
                        [f.id],
                    )
        elif code == "PAGE.NO_PAGE_NUMBERS":
            self.add(
                Proposal(
                    title="Add page numbers",
                    rationale="Multi-page documents need page numbers.",
                    ops=[AddPageNumbers(position="footer-center")],
                    risk="formatting_only",
                    before="No page numbers",
                    after="Page number in the footer",
                    finding_codes=[code],
                ),
                [f.id],
            )
        elif code in ("FIG.NUMBERING", "TBL.NUMBERING"):
            kind = "figure" if code.startswith("FIG") else "table"
            if kind not in numbering_done:
                numbering_done.add(kind)
                self._renumber(kind, False, [f.id], None)
        elif code == "REF.ORDER":
            numeric = all(re.match(r"^\s*(\[\d+\]|\d+\.)", r.text) for r in self._refs())
            self._sort_refs("numeric" if numeric else "alphabetical", [f.id], None)
        elif code == "SLIDE.OFF_SLIDE" and node and self.adm.slide_size and isinstance(f.actual, list | tuple):
            w, h = self.adm.slide_size
            x0, y0, x1, y1 = f.actual
            bw, bh = min(x1 - x0, w - 36), min(y1 - y0, h - 36)
            nx, ny = min(max(x0, 18), w - 18 - bw), min(max(y0, 18), h - 18 - bh)
            self.add(
                Proposal(
                    title="Move the shape inside the slide",
                    rationale="Content outside the slide is cut off.",
                    ops=[FitShape(node_id=node, bbox_pt=(nx, ny, nx + bw, ny + bh))],
                    risk="formatting_only",
                    before=f"x {x0:.0f}–{x1:.0f}, y {y0:.0f}–{y1:.0f} pt",
                    after=f"x {nx:.0f}–{nx + bw:.0f}, y {ny:.0f}–{ny + bh:.0f} pt",
                    node_ids=[node],
                    finding_codes=[code],
                ),
                [f.id],
            )
        elif code == "SLIDE.FONT_TOO_SMALL" and node:
            self.add(
                Proposal(
                    title="Raise text to at least 12 pt",
                    rationale="Small text is unreadable when presented.",
                    ops=[SetShapeFontMin(node_id=node, min_pt=12)],
                    risk="formatting_only",
                    before=f"{f.actual} pt",
                    after="≥ 12 pt",
                    node_ids=[node],
                    finding_codes=[code],
                ),
                [f.id],
            )

    def _plan_rule(self, f: FindingRef, rule: Rule, numbering_done: set[str]) -> None:
        c, strategy, node = rule.check, rule.fix.strategy, (f.node_ids[0] if f.node_ids else None)
        val = c.value if c.value is not None else (c.values[0] if c.values else None)
        common = {"rule_id": rule.id, "finding_codes": [f.code]}
        if strategy == "set_margins" and c.property and isinstance(val, int | float):
            side = c.property.split(".")[1]
            pt = round(to_pt(val, c.unit), 2)
            self.add(
                Proposal(
                    title=f"Set {side} margin to {val:g} {c.unit}",
                    rationale=rule.title,
                    risk="formatting_only",
                    ops=[SetPageSetup(margins_pt={side: pt})],
                    before=str(f.actual),
                    after=f"{val:g} {c.unit}",
                    **common,
                ),
                [f.id],
            )
        elif strategy == "set_paper" and val in ("Letter", "A4"):
            self.add(
                Proposal(
                    title=f"Use {val} paper",
                    rationale=rule.title,
                    risk="formatting_only",
                    ops=[SetPageSetup(paper=val)],
                    before=str(f.actual),
                    after=str(val),
                    **common,
                ),
                [f.id],
            )
        elif strategy == "set_columns" and isinstance(val, int):
            self.add(
                Proposal(
                    title=f"Use {val} columns",
                    rationale=rule.title,
                    risk="structural",
                    ops=[SetPageSetup(columns=val)],
                    before=str(f.actual),
                    after=str(val),
                    **common,
                ),
                [f.id],
            )
        elif strategy == "set_body_font" and node:
            if c.property == "font_family" and val:
                op = SetRunFmt(node_ids=[node], font_family=str(val))
                after = str(val)
            elif c.property == "size_pt":
                size = val if isinstance(val, int | float) else None
                if size is None and isinstance(f.actual, int | float):
                    lo, hi = c.min or f.actual, c.max or f.actual
                    size = min(max(f.actual, lo), hi)
                if size is None:
                    return
                op, after = SetRunFmt(node_ids=[node], size_pt=float(size)), f"{size:g} pt"
            else:
                return
            self.add(
                Proposal(
                    title=f"{rule.title}: {after}",
                    rationale=rule.title,
                    risk="formatting_only",
                    ops=[op],
                    before=str(f.actual),
                    after=after,
                    node_ids=[node],
                    **common,
                ),
                [f.id],
            )
        elif strategy == "set_line_spacing" and node and isinstance(val, int | float):
            self.add(
                Proposal(
                    title=f"Line spacing {val:g}",
                    rationale=rule.title,
                    risk="formatting_only",
                    ops=[SetParaFmt(node_ids=[node], line_spacing=float(val))],
                    before=str(f.actual),
                    after=f"{val:g}",
                    node_ids=[node],
                    **common,
                ),
                [f.id],
            )
        elif strategy == "set_alignment" and node and val in ("left", "center", "right", "justify"):
            self.add(
                Proposal(
                    title=f"Align {val}",
                    rationale=rule.title,
                    risk="formatting_only",
                    ops=[SetParaFmt(node_ids=[node], alignment=val)],
                    before=str(f.actual),
                    after=str(val),
                    node_ids=[node],
                    **common,
                ),
                [f.id],
            )
        elif strategy == "add_page_numbers":
            pos = "header-right" if self.family in ("apa", "mla") else "footer-center"
            self.add(
                Proposal(
                    title="Add page numbers",
                    rationale=rule.title,
                    risk="formatting_only",
                    ops=[AddPageNumbers(position=pos)],
                    before="No page numbers",
                    after=f"Page number ({pos.replace('-', ' ')})",
                    **common,
                ),
                [f.id],
            )
        elif strategy == "rename_heading" and node and c.pattern:
            target = c.pattern.strip("^$").replace("\\", "").title()
            old = self._text(node)
            self.add(
                Proposal(
                    title=f"Rename heading to “{target}”",
                    rationale=rule.title,
                    risk="content_change",
                    ops=[ReplaceText(node_id=node, before=old, after=target)],
                    before=old,
                    after=target,
                    node_ids=[node],
                    **common,
                ),
                [f.id],
            )
        elif strategy == "sort_references" and isinstance(c.value, str):
            self._sort_refs(c.value, [f.id], rule.id)
        elif strategy == "renumber_captions":
            kind = rule.selector.where.get("target_kind", "figure")
            if kind not in numbering_done:
                numbering_done.add(kind)
                self._renumber(kind, bool(c.pattern and "IVX" in c.pattern), [f.id], rule.id)
        elif strategy == "relabel_captions":
            ops: list[Operation] = []
            for cap in self._captions("figure"):
                if cap.label.lower() != "fig.":
                    new = re.sub(rf"^\s*{re.escape(cap.label)}", "Fig.", cap.text, count=1)
                    ops.append(ReplaceText(node_id=cap.id, before=cap.text, after=new))
            if ops:
                self.add(
                    Proposal(
                        title="Label figure captions “Fig.”",
                        rationale=rule.title,
                        risk="content_change",
                        ops=ops,
                        before="Figure 1.",
                        after="Fig. 1.",
                        **common,
                    ),
                    [f.id],
                )


def plan(
    adm: AdmDocument, findings: list[FindingRef], rules: dict[str, Rule] | None = None, family: str | None = None
) -> list[Planned]:
    return Planner(adm, rules, family).plan(findings)


def caption_number(c: Caption) -> int | None:
    return label_number(c.number)
