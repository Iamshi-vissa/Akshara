# ADR 0006 — Reference verification against public registries

Status: accepted (Phase 9)

**Context.** The product must never fabricate references. Verifying a citation needs an
authority outside the document; the obvious ones are Crossref (most DOIs) and OpenAlex
(broader coverage, including many non-Crossref DOIs).

**Decision.**
- A reference is `verified` only when a registry record exists for its DOI *and* the title,
  year (±1, online-first vs print) and first author written by the author agree with it.
  A DOI that resolves to a different work is a `mismatch`; an unknown DOI is `not_found`.
- Entries without a DOI are searched by title and first author. A result is offered only as a
  `possible_match` when title (≥ 0.92 similarity), first author and year all agree, and only
  the user can accept it. A short generic title contained in a longer one does not count as a
  match (a real false positive found while recording fixtures: a chapter titled "Notes").
- Suggested corrections are formatted from registry fields only (APA 7, IEEE, MLA 9 via a small
  formatter, not citeproc-py) and applied through the approval-gated change flow.
- Only public bibliographic text leaves the server, with a generic client name — no user
  identifiers or document content. Lookups run only when a user starts a check, and the whole
  feature can be switched off (`AKSHARA_REFERENCE_LOOKUPS=false`).
- Link checks refuse non-http(s) schemes, non-default ports, embedded credentials, internal
  names and private/reserved addresses, re-validating every redirect hop. Behind an egress
  proxy, name resolution happens at the proxy, so its policy is the address-level control; a
  link the server may not reach is reported "not checked", never "broken".
- Registry outages or rate limits (429/503 are retried honouring Retry-After) produce `error`,
  meaning "nothing concluded" — never `verified`, never a finding.

**Testing.** Real responses are recorded once (`tests/fixtures/scholarly/replay.py record`) and
replayed; a request that was not recorded fails the test, so tests cannot pass on invented data.
`AKSHARA_TEST_NETWORK=1` runs a live check.

**Consequences.** Results are stored as an inspection run of kind `references` (no new table).
A standalone reference library, BibTeX/RIS import and source discovery are deferred.
