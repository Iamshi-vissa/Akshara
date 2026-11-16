import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, json, type DocumentOut, type DraftOut } from '@/api/client';
import { runJob } from '@/api/jobs';
import { useCapabilities } from '@/components/layout/AppShell';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';

import { DraftBadge } from './CreatePage';

interface Section { id: string; title: string; level: number; target_words: number; notes: string }
const words = (t: string) => (t.match(/\w+/g) ?? []).length;
const isRefs = (t: string) => /^(references|bibliography|works cited|sources)$/i.test(t.trim());

export function DraftPage() {
  const { draftId = '' } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const caps = useCapabilities();
  const ai = caps.data?.capabilities.find((c) => c.key === 'ai_generate');
  const q = useQuery({ queryKey: ['generation', 'draft', draftId], queryFn: () => api<DraftOut>(`/generation/drafts/${draftId}`) });
  const [outline, setOutline] = useState<Section[] | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [refs, setRefs] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(true);
  const loaded = useRef(false);

  useEffect(() => {
    if (q.data && !loaded.current) {
      loaded.current = true;
      setOutline(q.data.outline as unknown as Section[]);
      setTexts(Object.fromEntries(Object.entries(q.data.sections).map(([k, v]) => [k, String((v as { text?: string }).text ?? '')])));
      setRefs(q.data.references.join('\n'));
    }
  }, [q.data]);

  const save = useMutation({
    mutationFn: () => api<DraftOut>(`/generation/drafts/${draftId}`, {
      method: 'PATCH', ...json({ outline, sections: texts, references: (refs ?? '').split('\n').map((r) => r.trim()).filter(Boolean) }),
    }),
    onSuccess: (d) => {
      qc.setQueryData(['generation', 'draft', draftId], d);
      setSaved(true);
    },
    onError: (e) => setError((e as ApiError).message),
  });
  // Autosave a moment after the last keystroke.
  useEffect(() => {
    if (saved || !loaded.current) return;
    const t = setTimeout(() => save.mutate(), 1200);
    return () => clearTimeout(t);
  }, [saved, outline, texts, refs]); // eslint-disable-line react-hooks/exhaustive-deps

  const reload = async () => {
    const d = await qc.fetchQuery({ queryKey: ['generation', 'draft', draftId], queryFn: () => api<DraftOut>(`/generation/drafts/${draftId}`) });
    setOutline(d.outline as unknown as Section[]);
    setTexts(Object.fromEntries(Object.entries(d.sections).map(([k, v]) => [k, String((v as { text?: string }).text ?? '')])));
  };
  const aiOutline = useMutation({
    mutationFn: async () => {
      if (!saved) await save.mutateAsync();
      return runJob(`/generation/drafts/${draftId}/outline`);
    },
    onSuccess: reload,
    onError: (e) => setError((e as Error).message),
  });
  const aiSection = useMutation({
    mutationFn: async (sid: string) => {
      if (!saved) await save.mutateAsync();
      return runJob(`/generation/drafts/${draftId}/sections/${sid}/generate`);
    },
    onSuccess: reload,
    onError: (e) => setError((e as Error).message),
  });
  const finalize = useMutation({
    mutationFn: async () => {
      if (!saved) await save.mutateAsync();
      return api<DocumentOut>(`/generation/drafts/${draftId}/finalize`, { method: 'POST' });
    },
    onSuccess: (doc) => navigate(`/documents/${doc.id}`),
    onError: (e) => setError((e as Error).message),
  });

  if (q.isPending || !outline) return <div className="surface mx-auto h-96 max-w-6xl animate-pulse" />;
  const d = q.data!;
  if (d.status === 'finalized') {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <h1 className="font-serif text-3xl">This draft is now a document</h1>
        {d.document_id && <Link className="mt-4 inline-block text-accent" to={`/documents/${d.document_id}`}>Open it</Link>}
      </div>
    );
  }
  const change = (fn: () => void) => {
    fn();
    setSaved(false);
  };
  const move = (i: number, dir: -1 | 1) => change(() => setOutline((o) => {
    const next = [...(o ?? [])];
    const j = i + dir;
    if (j < 0 || j >= next.length) return next;
    [next[i], next[j]] = [next[j]!, next[i]!];
    return next;
  }));
  const total = Object.values(texts).reduce((n, t) => n + words(t), 0);
  const target = outline.reduce((n, s) => n + (s.target_words || 0), 0);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <Link to="/create" className="inline-flex items-center gap-2 text-sm text-paper-faint hover:text-paper"><Icon name="back" /> Create</Link>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="label text-gold/80">Draft</p>
          <h1 className="mt-1 font-serif text-4xl font-semibold">{d.title}</h1>
          <p className="mt-1 text-sm text-paper-faint">{total.toLocaleString()} / {target.toLocaleString()} words · {saved ? 'saved' : 'saving…'}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={!ai?.available} title={ai?.available ? undefined : ai?.note} loading={aiOutline.isPending} onClick={() => aiOutline.mutate()}>
            Suggest outline with AI
          </Button>
          <Button loading={finalize.isPending} onClick={() => finalize.mutate()}>Create document</Button>
        </div>
      </header>
      {!ai?.available && <p className="text-xs text-paper-faint">AI drafting: {ai?.note} You can still write every section yourself.</p>}
      {error && <p role="alert" className="text-sm text-sev-critical">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className="surface h-fit space-y-2 p-3 lg:sticky lg:top-4" aria-label="Outline">
          <p className="label px-1">Outline</p>
          <ol className="space-y-1">
            {outline.map((s, i) => (
              <li key={s.id} className="flex items-center gap-1 rounded-md px-1 py-1 hover:bg-ink-800" style={{ paddingLeft: `${(s.level - 1) * 0.8 + 0.25}rem` }}>
                <input value={s.title} aria-label="Section title"
                  onChange={(e) => change(() => setOutline((o) => o!.map((x) => (x.id === s.id ? { ...x, title: e.target.value } : x))))}
                  className="min-w-0 flex-1 rounded bg-transparent px-1 text-sm outline-none focus:bg-ink-900" />
                <select value={s.level} aria-label="Level" onChange={(e) => change(() => setOutline((o) => o!.map((x) => (x.id === s.id ? { ...x, level: Number(e.target.value) } : x))))}
                  className="rounded bg-ink-900 text-xs text-paper-faint">
                  {[1, 2, 3].map((l) => <option key={l} value={l}>H{l}</option>)}
                </select>
                <button type="button" aria-label="Move up" onClick={() => move(i, -1)} className="px-1 text-paper-faint hover:text-paper">↑</button>
                <button type="button" aria-label="Move down" onClick={() => move(i, 1)} className="px-1 text-paper-faint hover:text-paper">↓</button>
                <button type="button" aria-label="Remove section" onClick={() => change(() => setOutline((o) => o!.filter((x) => x.id !== s.id)))} className="px-1 text-paper-faint hover:text-sev-critical">×</button>
              </li>
            ))}
          </ol>
          <Button size="sm" variant="ghost" onClick={() => change(() => setOutline((o) => [...o!, { id: Math.random().toString(36).slice(2, 12), title: 'New section', level: 1, target_words: 200, notes: '' }]))}>
            + Add section
          </Button>
        </aside>

        <div className="min-w-0 space-y-5">
          {outline.map((s) => {
            const meta = (d.sections[s.id] ?? {}) as { origin?: string; citations_removed?: string[]; model?: string };
            if (isRefs(s.title)) {
              return (
                <section key={s.id} className="surface p-5">
                  <h2 className="font-serif text-xl font-semibold">{s.title}</h2>
                  <p className="mt-1 text-xs text-paper-faint">One reference per line. Numbered citations [1], [2]… refer to this list in order.</p>
                  <textarea value={refs ?? ''} rows={5} onChange={(e) => change(() => setRefs(e.target.value))} aria-label="References"
                    className="mt-3 w-full rounded-lg border border-ink-600 bg-ink-900/80 p-3 font-mono text-xs" />
                </section>
              );
            }
            const n = words(texts[s.id] ?? '');
            const pct = s.target_words ? n / s.target_words : 0;
            return (
              <section key={s.id} className="surface p-5" aria-label={s.title}>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className={`font-serif font-semibold ${s.level === 1 ? 'text-xl' : 'text-lg'}`}>{s.title}</h2>
                  <DraftBadge origin={meta.origin} />
                  <span className={`ml-auto font-mono text-xs ${pct > 1.25 || (n > 0 && pct < 0.6) ? 'text-sev-medium' : 'text-paper-faint'}`}>
                    {n} / {s.target_words || '—'} words
                  </span>
                  <Button size="sm" variant="secondary" disabled={!ai?.available} loading={aiSection.isPending && aiSection.variables === s.id} onClick={() => aiSection.mutate(s.id)}>
                    Draft with AI
                  </Button>
                </div>
                {(meta.citations_removed?.length ?? 0) > 0 && (
                  <p className="mt-2 rounded border border-sev-medium/30 bg-sev-medium/10 px-2 py-1 text-xs text-sev-medium">
                    Removed citations not in your reference list: {meta.citations_removed!.join(', ')} — marked “[citation needed]”.
                  </p>
                )}
                {meta.model && <p className="mt-1 text-xs text-paper-faint">Drafted by {meta.model}. Check every claim before using it.</p>}
                <textarea value={texts[s.id] ?? ''} rows={Math.max(4, Math.min(20, Math.ceil((texts[s.id]?.length ?? 0) / 100)))}
                  onChange={(e) => change(() => setTexts((t) => ({ ...t, [s.id]: e.target.value })))}
                  placeholder={s.notes || 'Write this section. Separate paragraphs with a blank line.'} aria-label={`${s.title} text`}
                  className="mt-3 w-full rounded-lg border border-ink-600 bg-ink-900/60 p-3 text-sm leading-relaxed" />
              </section>
            );
          })}
          <p className="text-xs text-paper-faint">Sections left empty are omitted from the document. <Badge>autosaves</Badge></p>
        </div>
      </div>
    </div>
  );
}
