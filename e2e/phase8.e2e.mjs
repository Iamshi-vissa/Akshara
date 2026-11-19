/**
 * Phase 8 end-to-end check: upload a document with known visual defects, open the Visual tab,
 * and confirm the defects are listed and outlined on the page (needs the stack running).
 *
 *   node e2e/phase8.e2e.mjs <visual_defects.docx> [screenshot-dir]
 *
 * Build the file with: (cd backend && uv run python -m tests.fixtures.builders <dir>)
 */
import { createRequire } from 'node:module';
import path from 'node:path';

const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.AKSHARA_WEB_URL ?? 'http://localhost:5173';
const [file, shots] = process.argv.slice(2);
if (!file) throw new Error('usage: node e2e/phase8.e2e.mjs <visual_defects.docx> [screenshot-dir]');

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
const email = `p8-${Date.now()}@example.com`;
await p.request.post(`${BASE}/api/v1/auth/register`, { data: { email, password: 'Analytical-1843' } });
await p.goto(`${BASE}/login`);
await p.getByLabel('E-mail').fill(email);
await p.getByLabel('Password').fill('Analytical-1843');
await p.getByRole('button', { name: /^sign in$/i }).click();
await p.waitForURL(`${BASE}/`);
await p.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Library', exact: true }).click();
await p.getByLabel('Choose files to upload').setInputFiles(path.resolve(file));
await p.getByText('Stored securely as version 1').waitFor({ timeout: 60000 });
await p.locator('tbody').getByText('visual_defects', { exact: true }).click();
await p.getByRole('tab', { name: 'Visual' }).click();
const list = p.getByRole('list', { name: 'Visual findings' });
await list.getByText('into the margin', { exact: false }).first().waitFor({ timeout: 120000 });
const items = await list.getByRole('listitem').count();
await list.getByRole('button').filter({ hasText: 'margin' }).first().click();
await p.locator('img[alt="Page 1"]').evaluate((el) => el.scrollIntoView({ block: 'end' }));
await p.waitForTimeout(1500);
if (shots) await p.screenshot({ path: path.join(shots, 'p8-visual.png') });
console.log(`visual findings listed: ${items}`);
if (items < 4) throw new Error('expected at least four visual findings');
await b.close();
