/**
 * Phase 7 end-to-end check: outline -> themed deck -> analysed document (needs the stack running).
 *
 *   node e2e/phase7.e2e.mjs [screenshot-dir]
 */
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
const S = process.argv[2] ?? '.';
const BASE = process.env.AKSHARA_WEB_URL ?? 'http://localhost:5173';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
const email = `p7-${Date.now()}@example.com`;
await p.request.post(`${BASE}/api/v1/auth/register`, { data: { email, password: 'Analytical-1843' } });
await p.goto(BASE + '/login');
await p.getByLabel('E-mail').fill(email);
await p.getByLabel('Password').fill('Analytical-1843');
await p.getByRole('button', { name: /^sign in$/i }).click();
await p.waitForURL(`${BASE}/`);
await p.getByRole('link', { name: 'Slides' }).click();
await p.getByText('From an outline').click();
await p.getByText('Ink (dark, high contrast)').click();
await p.screenshot({ path: `${S}/p7-form.png`, fullPage: true });
await p.getByRole('button', { name: 'Generate presentation' }).click();
await p.waitForURL(/\/documents\//, { timeout: 120000 });
await p.waitForTimeout(2500);
await p.screenshot({ path: `${S}/p7-doc.png` });
console.log('landed', p.url());
await b.close();
