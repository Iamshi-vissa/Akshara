from __future__ import annotations

from app.domain.generation.citations import NEEDED, sanitize
from app.domain.generation.style import from_profile
from app.domain.generation.templates import KINDS, new_outline
from app.standards import builtin_profiles


def test_only_supplied_references_survive() -> None:
    text = (
        "Prior work exists [1]. Others agree [2, 3]. A range [1-2]. Smith (Smith, 2019) said so. "
        "See doi:10.1000/xyz123 and https://example.com/paper."
    )
    out, rep = sanitize(text, allowed=2)
    assert "[1]" in out and "[1-2]" in out
    assert "[2, 3]" not in out and "(Smith, 2019)" not in out and "doi:" not in out and "https://" not in out
    assert out.count(NEEDED) == 4 and len(rep.removed) == 4


def test_no_references_means_no_citations() -> None:
    out, rep = sanitize("A claim [1].", allowed=0)
    assert out == f"A claim {NEEDED}." and rep.removed == ["[1]"]


def test_templates_cover_all_kinds_and_budget() -> None:
    assert len(KINDS) == 10
    for kind in KINDS:
        outline = new_outline(kind, 1000)
        assert outline and all(o["title"] for o in outline)
        assert abs(sum(o["target_words"] for o in outline) - 1000) <= 10 * len(outline)


def test_style_from_standards() -> None:
    apa = from_profile(builtin_profiles()["apa-7"])
    assert apa.margins_pt == (72.0, 72.0, 72.0, 72.0) and apa.line_spacing == 2.0 and apa.page_numbers == "header-right"
    ieee = from_profile(builtin_profiles()["ieee-conference-letter"])
    assert ieee.margins_pt == (54.0, 72.0, 45.0, 45.0) and ieee.columns == 2 and ieee.size_pt == 10.0
    mla = from_profile(builtin_profiles()["mla-9"])
    assert mla.references_title == "Works Cited"
