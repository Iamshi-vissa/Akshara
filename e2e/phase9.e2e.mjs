/**
 * Phase 9 end-to-end check against the running stack and the LIVE registries (Crossref/OpenAlex):
 *  1. upload a document with known reference problems, check its references, propose a fix;
 *  2. build a custom standard from pasted guideline text through the review queue.
 *
 *   node e2e/phase9.e2e.mjs <reference_checks.docx> [screenshot-dir]
 *
 * Build the file with: (cd backend && uv run python -m tests.fixtures.builders <dir>)
 */
import { createRequire } from 'node:module';
import path from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.AKSHARA_WEB_URL ?? 'http://localhost:5173';
const [file, shots] = process.argv.slice(2);
if (!file) throw new Error('usage: node e2e/phase9.e2e.mjs <reference_checks.docx> [screenshot-dir]');
const shot = async (p, name) => shots && p.screenshot({ path: path.join(shots, name), fullPage: true });
const check = (ok, msg) => {
  if (!ok) throw new Error(`FAIL: ${msg}`);
  console.log(`ok - ${msg}`);
};

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
const email = `p9-${Date.now()}@example.com`;
await p.request.post(`${BASE}/api/v1/auth/register`, { data: { email, password: 'Analytical-1843' } });
await p.goto(`${BASE}/login`);
await p.getByLabel('E-mail').fill(email);
await p.getByLabel('Password').fill('Analytical-1843');
await p.getByRole('button', { name: /^sign in$/i }).click();
await p.waitForURL(`${BASE}/`);

// 1. References
await p.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Library', exact: true }).click();
await p.getByLabel('Choose files to upload').setInputFiles(path.resolve(file));
await p.getByText('Stored securely as version 1').waitFor({ timeout: 60000 });
await p.locator('tbody').getByText('reference_checks', { exact: true }).click();
await p.getByRole('tab', { name: 'References' }).click();
await p.getByRole('button', { name: 'Check references' }).click();
const list = p.getByRole('list', { name: 'References' });
await list.getByText('Verified', { exact: true }).waitFor({ timeout: 180000 });
const count = async (label) => list.getByText(label, { exact: true }).count();
check((await count('Verified')) === 1, 'the correct DOI is verified');
check((await count('DOI not registered')) === 2, 'two unregistered DOIs are reported');
check((await count('Does not match its DOI')) === 1, 'the wrong title for a real DOI is caught');
check((await count('Possible match — confirm')) === 1, 'a DOI-less real paper gets a match to confirm');
check((await count('Not verifiable')) === 1, 'the invented reference is not "verified" by anything');
await shot(p, 'p9-references.png');
const mismatch = list.getByRole('listitem').filter({ hasText: 'Does not match its DOI' });
check((await mismatch.getByText('"Deep learning,"', { exact: false }).count()) > 0, 'correction comes from the registered record');
await mismatch.getByRole('button', { name: 'Propose this correction' }).click();
await mismatch.getByRole('link', { name: /review it in Changes/ }).click();
await p.getByText('Edit paragraph', { exact: false }).first().waitFor({ timeout: 15000 });
check(true, 'the correction waits for approval in Changes');

// 2. Standard builder
await p.goto(`${BASE}/standards`);
await p.getByRole('link', { name: 'Build from guidelines' }).click();
await p.getByLabel('…or paste the text').fill(
  'All pages must use A4 paper. Use margins of 2.5 cm on all sides. The text must be 12-point Times New Roman and double-spaced.',
);
await p.getByRole('button', { name: 'Find rules' }).click();
await p.getByRole('heading', { name: /Review \d+ proposed rule/ }).waitFor({ timeout: 20000 });
const grounded = await p.getByText('Grounded in the text').count();
check(grounded >= 4, `${grounded} rules proposed, each grounded in a quoted sentence`);
await shot(p, 'p9-builder.png');
await p.getByLabel('Standard name').fill('Department thesis guide');
await p.getByRole('button', { name: /Create draft with \d+ rule/ }).click();
await p.waitForURL(/\/standards\/[0-9a-f-]{36}$/, { timeout: 15000 });
await p.getByText('Department thesis guide').first().waitFor();
check(true, 'draft standard created from the reviewed rules');
await b.close();
