from __future__ import annotations

import pytest

from app.domain.adm.model import AdmDocument, Metadata
from app.domain.inspection import InspectContext, inspect
from app.domain.inspection.checks.visual import contrast_ratio


def _ctx(pages: list[dict], fmt: str = "pdf") -> InspectContext:
    adm = AdmDocument(source_format=fmt, body=[], metadata=Metadata(title="t", authors=["a"]))
    return InspectContext(adm=adm, layout={"pages": pages})


def _span(x0: float, y0: float, x1: float, y1: float, text: str = "Some text", size: float = 12, **kw) -> dict:
    return {"text": text, "bbox": [x0, y0, x1, y1], "size": size, "font": "Times", **kw}


def _page(i: int, spans: list[dict], **kw) -> dict:
    return {"index": i, "width_pt": 612, "height_pt": 792, "blank": False, "spans": spans, "images": [], **kw}


def _codes(ctx: InspectContext) -> dict[str, list]:
    out: dict[str, list] = {}
    for f in inspect(ctx).findings:
        if f.category == "visual":
            out.setdefault(f.code, []).append(f)
    return out


def test_contrast_ratio_matches_wcag_reference_values() -> None:
    assert contrast_ratio(0x000000, 0xFFFFFF) == pytest.approx(21.0)
    assert contrast_ratio(0x777777, 0xFFFFFF) == pytest.approx(4.48, abs=0.01)
    assert contrast_ratio(0xFFFFFF, 0xFFFFFF) == pytest.approx(1.0)


def test_overlapping_text_is_found_but_adjacent_spans_are_not() -> None:
    spans = [
        _span(72, 100, 300, 114),
        _span(300, 100, 400, 114),  # same line, touching: fine
        _span(80, 104, 290, 118),  # collides with the first line
    ]
    found = _codes(_ctx([_page(0, spans)]))
    assert list(found) == ["VIS.TEXT_OVERLAP"]
    assert found["VIS.TEXT_OVERLAP"][0].actual["count"] == 2
    assert found["VIS.TEXT_OVERLAP"][0].bbox == (72, 100, 300, 118)


def test_sparse_page_after_a_full_page() -> None:
    full = [_span(72, 80 + 22 * i, 540, 94 + 22 * i) for i in range(28)]
    pages = [_page(0, full), _page(1, [_span(72, 80, 300, 94)]), _page(2, full)]
    assert "VIS.SPARSE_PAGE" in _codes(_ctx(pages))


def test_low_contrast_respects_large_text_threshold() -> None:
    grey = 0x949494  # 3.0:1 on white
    spans = [
        _span(72, 100, 300, 114, color=grey, bg=0xFFFFFF),  # small: needs 4.5
        _span(72, 140, 300, 170, size=24, color=grey, bg=0xFFFFFF),  # large: 3.0 is enough
    ]
    f = _codes(_ctx([_page(0, spans)]))["VIS.LOW_CONTRAST"][0]
    assert f.actual["count"] == 1


def test_old_renders_without_colour_are_not_evaluated() -> None:
    result = inspect(_ctx([_page(0, [_span(72, 100, 300, 114)])]))
    assert any(n["check"] == "VIS.LOW_CONTRAST" for n in result.not_evaluated)


def test_nothing_is_evaluated_without_a_render() -> None:
    adm = AdmDocument(source_format="pdf", body=[], metadata=Metadata(title="t", authors=["a"]))
    result = inspect(InspectContext(adm=adm, layout=None))
    assert {n["check"] for n in result.not_evaluated} >= {"VIS.CONTENT_OFF_PAGE", "VIS.TEXT_OVERLAP"}
