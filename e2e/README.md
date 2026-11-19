# End-to-end checks

`phase1.e2e.mjs` drives the real application in Chromium (Playwright): register, upload real
DOCX/PDF/PPTX files, verify the downloaded original is byte-identical (SHA-256), check that a
`.docm` file is refused, that unbuilt modules are shown as locked, that the refresh cookie is
httpOnly and invisible to JavaScript, and that the layout has no horizontal scroll at phone width.

```bash
node e2e/phase1.e2e.mjs path/to/samples [path/to/screenshots]
```

The samples folder needs `Research_Report.docx`, `Methodology_Paper.pdf`,
`Quarterly_Review.pptx` and `Thesis.docm` (any DOCX renamed). Set `AKSHARA_WEB_URL` to test
the Docker stack (`http://localhost:8080`); the default is the Vite dev server.

## Later phases

| Script | Checks | Input |
|---|---|---|
| `phase7.e2e.mjs [shots]` | outline → themed deck → analysed document | none |
| `phase8.e2e.mjs <visual_defects.docx> [shots]` | Visual tab lists the planted defects and draws them | built by `tests/fixtures/builders.py` |
| `phase9.e2e.mjs <reference_checks.docx> [shots]` | reference statuses against the **live** Crossref/OpenAlex, correction proposal, standard built from guideline text | built by `tests/fixtures/builders.py` |

Build the fixture files with `(cd backend && uv run python -m tests.fixtures.builders <dir>)`.
