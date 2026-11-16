import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, json, type ChangeSetOut, type DocumentOut, type VersionOut } from '@/api/client';
import { useCapabilities } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/Button';

interface Run { text: string }
interface Node { id: string; type: string; role?: string; level?: number; runs?: Run[] }
interface Slide { index: number; shapes: { paragraphs: Node[] }[] }
interface Adm { body: Node[]; slides: Slide[] }

const OPS = [
  ['clarity', 'Improve clarity'],
  ['grammar', 'Fix grammar'],
  ['academic', 'Academic register'],
  ['professional', 'Professional register'],
  ['paraphrase', 'Paraphrase'],
  ['summarize', 'Summarise'],
  ['expand', 'Expand'],
  ['restructure', 'Restructure sentences'],
] as const;

const textOf = (n: Node) => (n.runs ?? []).map((r) => r.text).join('');

export function EditPanel({ doc, version }: { doc: DocumentOut; version: VersionOut }) {
  const qc = useQueryClient();
  const [, setParams] = useSearchParams();
  const caps = useCapabilities();
  const ai = caps.data?.capabilities.find((c) => c.key === 'ai_edit');
  const adm = useQuery({ queryKey: ['versions', version.id, 'adm'], queryFn: () => api<Adm>(`/versions/${version.id}/adm`) });
  const nodes = useMemo(() => {
    const a = adm.data;
    if (!a) return [];
    const body = a.body.filter((n) => ['paragraph', 'heading', 'caption'].includes(n.type) && n.role !== 'empty' && textOf(n).trim());
    const slides = a.slides.flatMap((s) => s.shapes.flatMap((sh) => sh.paragraphs.filter((p) => textOf(p).trim())));
    return [...body, ...slides];
  }, [adm.data]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [op, setOp] = useState<string>('clarity');
  const [error, setError] = useState<string | null>(null);

  const goReview = (c: ChangeSetOut) => {
    qc.setQueryData(['changesets', c.id], c);
    void qc.invalidateQueries({ queryKey: ['documents', doc.id, 'changesets'] });
    setEdits({});
    setPicked(new Set());
    setParams((p) => {
      p.set('tab', 'changes');
      return p;
    });
  };
  const saveManual = useMutation({
    mutationFn: () => api<ChangeSetOut>(`/documents/${doc.id}/changesets`, {
      method: 'POST', ...json({ source: 'manual', edits: Object.entries(edits).map(([node_id, after]) => ({ node_id, after })) }),
    }),
    onSuccess: goReview,
    onError: (e) => setError((e as ApiError).message),
  });
  const askAi = useMutation({
    mutationFn: () => api<ChangeSetOut>(`/documents/${doc.id}/changesets`, {
      method: 'POST', ...json({ source: 'ai_edit', operation: op, node_ids: [...picked] }),
    }),
    onSuccess: goReview,
    onError: (e) => setError((e as ApiError).message),
  });

  if (doc.kind === 'pdf') return <p className="text-sm text-paper-dim">PDF text cannot be edited in place. Edit the source document instead.</p>;
  if (adm.isPending) return <div className="surface h-64 animate-pulse" />;
  const changed = Object.keys(edits).length;

  return (
    <div className="space-y-4">
      <section className="surface sticky top-2 z-10 flex flex-wrap items-center gap-3 p-3">
        <span className="text-sm text-paper-dim">{changed} paragraph{changed === 1 ? '' : 's'} edited · {picked.size} selected</span>
        <Button size="sm" disabled={!changed} loading={saveManual.isPending} onClick={() => saveManual.mutate()}>Review my edits</Button>
        <span className="mx-1 h-6 w-px bg-ink-700" aria-hidden />
        <select value={op} onChange={(e) => setOp(e.target.value)} disabled={!ai?.available} aria-label="AI action"
          className="h-8 rounded-lg border border-ink-600 bg-ink-900 px-2 text-sm disabled:opacity-50">
          {OPS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <Button size="sm" variant="secondary" disabled={!ai?.available || picked.size === 0} loading={askAi.isPending} onClick={() => askAi.mutate()}>
          Suggest with AI
        </Button>
        {!ai?.available && <span className="text-xs text-paper-faint">AI assistant: {ai?.note}</span>}
        {error && <p role="alert" className="w-full text-sm text-sev-critical">{error}</p>}
      </section>
      <p className="text-xs text-paper-faint">
        Edits are never applied directly: they become proposals you review in the Changes tab, and applying them creates a new version.
        AI suggestions only use paragraphs you select, and only if you allowed external AI providers in Settings.
      </p>
      <ol className="space-y-2">
        {nodes.map((n) => {
          const original = textOf(n);
          const value = edits[n.id] ?? original;
          const isHeading = n.type === 'heading';
          return (
            <li key={n.id} className={`flex gap-3 rounded-xl border p-3 ${edits[n.id] !== undefined ? 'border-accent/50 bg-accent-soft' : 'border-ink-700 bg-ink-850/60'}`}>
              <input type="checkbox" aria-label="Select for AI" checked={picked.has(n.id)} disabled={!ai?.available}
                onChange={(e) => setPicked((s) => {
                  const next = new Set(s);
                  if (e.target.checked) next.add(n.id);
                  else next.delete(n.id);
                  return next;
                })} className="mt-1.5 accent-[#8b93ff]" />
              <div className="min-w-0 flex-1">
                <span className="label">{isHeading ? `Heading ${n.level}` : n.type === 'caption' ? 'Caption' : n.role === 'reference_entry' ? 'Reference' : 'Paragraph'}</span>
                <textarea
                  value={value}
                  rows={Math.min(8, Math.max(1, Math.ceil(value.length / 110)))}
                  onChange={(e) => setEdits((ed) => {
                    const next = { ...ed };
                    if (e.target.value === original) delete next[n.id];
                    else next[n.id] = e.target.value;
                    return next;
                  })}
                  aria-label={`Text of ${n.id}`}
                  className={`mt-1 w-full resize-y rounded-md border border-transparent bg-transparent p-1 text-paper outline-none focus:border-ink-600 ${isHeading ? 'font-serif text-lg font-semibold' : 'text-sm leading-relaxed'}`}
                />
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
