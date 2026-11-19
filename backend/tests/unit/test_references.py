from __future__ import annotations

import asyncio

import httpx
import pytest

from app.adapters.urlcheck import UnsafeUrl, assert_safe, check_url
from app.domain.references.format import apa, ieee, mla, plain
from app.domain.references.match import compare, title_similarity
from app.domain.references.model import Person, Record
from app.domain.references.parse import clean_doi, parse_reference

OPTUNA = Record(
    title="Optuna: A Next-generation Hyperparameter Optimization Framework",
    authors=[Person("Akiba", "Takuya"), Person("Sano", "Shotaro"), Person("Yanase", "Toshihiko")],
    year=2019,
    container="Proceedings of the 25th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining",
    pages="2623-2631",
    publisher="ACM",
    doi="10.1145/3292500.3330701",
    type="proceedings-article",
)


@pytest.mark.parametrize(
    ("text", "authors", "year", "title"),
    [
        (
            '[1] T. Akiba, S. Sano, and M. Koyama, "Optuna: A framework," in Proc. KDD, 2019.',
            ["Akiba", "Sano", "Koyama"],
            2019,
            "Optuna: A framework",
        ),
        (
            "Akiba, T., Sano, S., & Koyama, M. (2019). Optuna: A framework. In Proc. KDD.",
            ["Akiba", "Sano", "Koyama"],
            2019,
            "Optuna: A framework",
        ),
        (
            'Akiba, Takuya, et al. "Optuna: A Framework." Proceedings of KDD, 2019.',
            ["Akiba"],
            2019,
            "Optuna: A Framework",
        ),
        (
            "[2] A. Author and B. Writer, Testing Documents at Scale. Example Press, 2021.",
            ["Author", "Writer"],
            2021,
            "Testing Documents at Scale",
        ),
    ],
)
def test_parse_styles(text: str, authors: list[str], year: int, title: str) -> None:
    p = parse_reference(text)
    assert (p.authors, p.year, p.title) == (authors, year, title)


def test_doi_and_urls() -> None:
    p = parse_reference('X. Y, "T," 2020. https://doi.org/10.1000/ABC.12). Available: https://example.org/a.')
    assert p.doi == "10.1000/abc.12" and p.urls == ["https://example.org/a"]
    assert clean_doi("doi: 10.1/X.") == "10.1/x"


def test_title_similarity_rejects_generic_containment() -> None:
    assert title_similarity("Notes on structured writing", "Notes") < 0.5  # regression: was 1.0
    assert title_similarity("Optuna", OPTUNA.title) < 0.5
    assert title_similarity("Optuna: A next-generation hyperparameter optimization framework", OPTUNA.title) == 1.0
    assert title_similarity("Array programming with NumPy", "Array programming with NumPy: a review") >= 0.9


def test_compare_reports_each_difference() -> None:
    p = parse_reference('[3] B. Smith, "Optuna: A next-generation hyperparameter optimization framework," 2012.')
    c = compare(p, OPTUNA)
    assert c.title == 1.0 and c.year_ok is False and c.author_ok is False and len(c.differences) == 2


def test_formatters_use_only_registry_fields() -> None:
    assert apa(OPTUNA).startswith("Akiba, T., Sano, S., & Yanase, T. (2019). Optuna: A Next-generation")
    assert "2623\u20132631" in apa(OPTUNA) and apa(OPTUNA).endswith("https://doi.org/10.1145/3292500.3330701")
    assert ieee(OPTUNA).startswith('T. Akiba, S. Sano, and T. Yanase, "Optuna:')
    assert mla(OPTUNA).startswith('Akiba, Takuya, et al. "Optuna:')
    book = Record(title="Structured Writing", authors=[Person("Writer", "B.")], publisher="Example Press")
    assert apa(book) == "Writer, B. (n.d.). Structured Writing."  # no invented year or publisher info
    assert "*" not in plain(apa(OPTUNA))


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/x",
        "http://127.0.0.1/",
        "http://10.1.2.3/a",
        "http://[::1]/",
        "http://169.254.169.254/",
        "https://user:pw@example.org/",
        "https://example.org:8443/",
        "http://localhost/",
        "http://db.internal/",
    ],
)
def test_ssrf_guard_refuses(url: str) -> None:
    with pytest.raises(UnsafeUrl):
        asyncio.run(assert_safe(url))


def test_check_url_follows_redirects_but_never_into_private_space() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/moved":
            return httpx.Response(301, headers={"location": "http://10.0.0.7/admin"})
        if req.url.path == "/gone":
            return httpx.Response(404)
        return httpx.Response(200, text="ok")

    t = httpx.MockTransport(handler)
    ok = asyncio.run(check_url("https://93.184.215.14/page", transport=t))
    gone = asyncio.run(check_url("https://93.184.215.14/gone", transport=t))
    moved = asyncio.run(check_url("https://93.184.215.14/moved", transport=t))
    assert ok.ok and ok.status == 200
    assert not gone.ok and gone.checked and gone.status == 404
    assert not moved.ok and "private" in moved.reason and moved.final_url == "http://10.0.0.7/admin"
