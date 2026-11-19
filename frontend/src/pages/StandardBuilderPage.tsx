import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, json, type StandardDetail } from '@/api/client';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { describeCheck, type UdseRule } from '@/features/standards/rules';

interface Candidate { rule: UdseRule; quote: string; evidence_verified: boolean; problems: string[] }
interface Extraction { source_name: string; characters: number; candidates: Candidate[] }
type Decision = 'accept' | 'reject';

/** Mark the quoted sentence's numbers so the reviewer can see where each value comes from. */
function Quote({ text }: { text: string }) {
  const parts = text.split(/(\d+(?:\.\d+)?)/);
  return (
    <blockquote className="border-l-2 border-gold/50 pl-3 text-sm text-paper-dim">
      “{parts.map((p, i) => (i % 2 ? <mark key={i} className="rounded bg-gold-soft px-0.5 text-gold">{p}</mark> : p))}”
    </blockquote>
  );
}

export function StandardBuilderPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [result, setResult] = useState<Extraction | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});

  const extract = useMutation({
    mutationFn: async (fd: FormData) => api<Extraction>('/standards/extract', { method: 'POST', body: fd }),
    onSuccess: (r) => {
      setResult(r);
      // Grounded candidates start accepted; anything that failed verification starts rejected.
      setDecisions(Object.fromEntries(r.candidates.map((c) => [c.rule.id, c.evidence_verified ? 'accept' : 'reject'])));
    },
  });
  const create = useMutation({
    mutationFn: (body: { name: string; description: string; extends: string | null; rules: UdseRule[] }) =>
      api<StandardDetail>('/standards', { method: 'POST', ...json(body) }),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ['standards'] });
      navigate(`/standards/${d.version_id}`);
    },
  });

  function onExtract(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const src = new FormData(e.currentTarget);
    const fd = new FormData();
    const file = src.get('file');
    if (file instanceof File && file.size > 0) fd.set('file', file);
    else fd.set('text', String(src.get('text') ?? ''));
    extract.mutate(fd);
  }
  function onCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const rules = (result?.candidates ?? []).filter((c) => decisions[c.rule.id] === 'accept').map((c) => c.rule);
    create.mutate({
      name: String(f.get('name')),
      description: `Built from ${result?.source_name ?? 'a guideline'}. ${String(f.get('description') ?? '')}`.trim(),
      extends: String(f.get('extends') || '') || null,
      rules,
    });
  }
  const accepted = Object.values(decisions).filter((d) => d === 'accept').length;

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <Link to="/standards" className="inline-flex items-center gap-2 text-sm text-paper-faint hover:text-paper"><Icon name="back" /> Standards</Link>
      <header>
        <p className="label text-gold/80">Custom standard</p>
        <h1 className="mt-1 font-serif text-4xl font-semibold">Build from your guidelines</h1>
        <p className="mt-2 max-w-2xl text-paper-dim">
          Upload a style guide or paste its text. AKSHARA proposes rules only where a sentence states them, shows that sentence
          next to each rule, and checks that every number in the rule appears in it. You decide which rules to keep; the file is
          read once and not stored.
        </p>
      </header>

      <form onSubmit={onExtract} className="surface grid gap-4 p-6" aria-label="Guideline">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-paper-dim">Guideline file (.docx, .pdf or .txt)</span>
          <input type="file" name="file" accept=".docx,.pdf,.txt" className="block w-full text-sm text-paper-dim file:mr-3 file:rounded-md file:border-0 file:bg-ink-700 file:px-3 file:py-2 file:text-paper" />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-paper-dim">…or paste the text</span>
          <textarea name="text" rows={5} className="w-full rounded-lg border border-ink-600 bg-ink-900/80 p-3 text-sm" placeholder="Use margins of 2.5 cm on all sides. The text must be 12-point Times New Roman…" />
        </label>
        {extract.isError && <p role="alert" className="text-sm text-sev-critical">{(extract.error as ApiError).message}</p>}
        <div><Button type="submit" loading={extract.isPending}>Find rules</Button></div>
      </form>

      {result && (
        <section aria-label="Review queue" className="space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-serif text-2xl font-semibold">Review {result.candidates.length} proposed rule{result.candidates.length === 1 ? '' : 's'}</h2>
            <p className="text-xs text-paper-faint">{result.source_name} · {result.characters.toLocaleString()} characters read</p>
          </div>
          {result.candidates.length === 0 && (
            <p className="surface p-4 text-sm text-paper-dim">No sentence in this text states a rule AKSHARA can check. You can still add rules by hand on the standard's page.</p>
          )}
          <ul className="space-y-3">
            {result.candidates.map((c) => {
              const d = decisions[c.rule.id];
              return (
                <li key={c.rule.id} className={`surface space-y-2 p-4 ${d === 'reject' ? 'opacity-60' : ''}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{c.rule.title}</span>
                    <code className="text-xs text-paper-faint">{describeCheck(c.rule)}</code>
                    {c.evidence_verified ? <Badge tone="ok">Grounded in the text</Badge> : <Badge tone="warn">Not grounded</Badge>}
                    <div className="ml-auto flex gap-1" role="radiogroup" aria-label={`Decision for ${c.rule.title}`}>
                      {(['accept', 'reject'] as const).map((k) => (
                        <button key={k} type="button" role="radio" aria-checked={d === k}
                          disabled={k === 'accept' && !c.evidence_verified}
                          onClick={() => setDecisions((x) => ({ ...x, [c.rule.id]: k }))}
                          className={`rounded-md px-3 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40 ${d === k ? (k === 'accept' ? 'bg-ok/20 text-ok' : 'bg-ink-700 text-paper') : 'text-paper-faint hover:text-paper'}`}>
                          {k === 'accept' ? 'Keep' : 'Discard'}
                        </button>
                      ))}
                    </div>
                  </div>
                  <Quote text={c.quote} />
                  {c.problems.length > 0 && <p className="text-xs text-sev-medium">{c.problems.join(' ')}</p>}
                </li>
              );
            })}
          </ul>

          {result.candidates.length > 0 && (
            <form onSubmit={onCreate} className="surface grid gap-4 p-6 md:grid-cols-2" aria-label="Create standard">
              <Field label="Standard name" name="name" required minLength={2} maxLength={200} />
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-paper-dim">Build on</span>
                <select name="extends" className="h-11 w-full rounded-lg border border-ink-600 bg-ink-900 px-3">
                  <option value="">Nothing — only these rules</option>
                  <option value="apa-7">APA 7</option>
                  <option value="ieee-conference-letter">IEEE conference</option>
                  <option value="mla-9">MLA 9</option>
                </select>
              </label>
              <Field label="Description (optional)" name="description" maxLength={1500} className="md:col-span-2" />
              {create.isError && <p role="alert" className="text-sm text-sev-critical md:col-span-2">{(create.error as ApiError).message}</p>}
              <div className="flex items-center gap-3 md:col-span-2">
                <Button type="submit" loading={create.isPending} disabled={accepted === 0}>Create draft with {accepted} rule{accepted === 1 ? '' : 's'}</Button>
                <span className="text-xs text-paper-faint">You can edit and then publish it on the next page.</span>
              </div>
            </form>
          )}
        </section>
      )}
    </div>
  );
}
