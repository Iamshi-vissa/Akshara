import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { useMutation, useQuery } from '@tanstack/react-query';

import { api, ApiError, json, type DraftOut, type KindOut, type StandardOut } from '@/api/client';
import BlurText from '@/components/reactbits/BlurText';
import SpotlightCard from '@/components/reactbits/SpotlightCard';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { relativeTime } from '@/lib/format';

const TONES = ['professional', 'academic', 'formal', 'neutral', 'persuasive', 'friendly'];

export function CreatePage() {
  const navigate = useNavigate();
  const kinds = useQuery({ queryKey: ['generation', 'kinds'], queryFn: () => api<KindOut[]>('/generation/kinds') });
  const drafts = useQuery({ queryKey: ['generation', 'drafts'], queryFn: () => api<DraftOut[]>('/generation/drafts') });
  const standards = useQuery({ queryKey: ['standards'], queryFn: () => api<StandardOut[]>('/standards') });
  const [kind, setKind] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<DraftOut>('/generation/drafts', { method: 'POST', ...json(body) }),
    onSuccess: (d) => navigate(`/create/${d.id}`),
  });
  const selected = kinds.data?.find((k) => k.key === kind);
  const stdOptions = (standards.data ?? []).flatMap((s) =>
    s.versions.filter((v) => s.builtin || v.status === 'published').map((v) => ({ id: v.id, label: s.name })),
  );

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const refs = String(f.get('references') ?? '').split('\n').map((r) => r.trim()).filter(Boolean);
    create.mutate({
      kind, title: f.get('title'), topic: f.get('topic'), instructions: f.get('instructions'), tone: f.get('tone'),
      word_target: Number(f.get('word_target')) || null, author: f.get('author') || null,
      citation_style: f.get('citation_style'), references: refs, standard_version_id: f.get('standard') || null,
    });
  }

  return (
    <div className="mx-auto max-w-6xl space-y-10">
      <header>
        <p className="label text-gold/80">Create document</p>
        <BlurText text="Start from a sound structure." className="mt-2 font-serif text-4xl font-semibold" animateBy="words" delay={60} trigger="load" />
        <p className="mt-2 max-w-2xl text-paper-dim">
          Pick a document type, adjust the outline, then write each section yourself or ask the assistant to draft it.
          Only references you supply are ever cited.
        </p>
      </header>

      {(drafts.data ?? []).filter((d) => d.status === 'draft').length > 0 && (
        <section>
          <h2 className="mb-3 font-serif text-xl font-semibold">Continue a draft</h2>
          <ul className="flex flex-wrap gap-2">
            {drafts.data!.filter((d) => d.status === 'draft').map((d) => (
              <li key={d.id}>
                <Link to={`/create/${d.id}`} className="surface inline-flex items-center gap-2 px-4 py-2 text-sm hover:border-ink-500">
                  {d.title} <span className="text-xs text-paper-faint">{relativeTime(d.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Document type">
        <h2 className="mb-4 font-serif text-xl font-semibold">1. Choose a type</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {(kinds.data ?? []).map((k) => (
            <button key={k.key} type="button" onClick={() => setKind(k.key)} aria-pressed={kind === k.key} className="h-full rounded-2xl text-left">
              <SpotlightCard className={`h-full rounded-2xl border p-4 transition-colors ${kind === k.key ? 'border-accent bg-accent-soft' : 'border-ink-700 bg-ink-850/80 hover:border-ink-500'}`}
                spotlightColor="rgba(139, 147, 255, 0.18)" theme="dark">
                <p className="font-medium">{k.label}</p>
                <p className="mt-1 text-xs text-paper-faint">~{k.words.toLocaleString()} words · {k.outline.length} sections</p>
              </SpotlightCard>
            </button>
          ))}
        </div>
      </section>

      {selected && (
        <form onSubmit={onSubmit} className="surface grid gap-5 p-6 md:grid-cols-2" aria-label="Brief">
          <h2 className="font-serif text-xl font-semibold md:col-span-2">2. Brief for your {selected.label.toLowerCase()}</h2>
          <Field label="Title" name="title" required minLength={2} maxLength={300} className="md:col-span-2" />
          <label className="block md:col-span-2">
            <span className="mb-1.5 block text-sm font-medium text-paper-dim">Topic and key points</span>
            <textarea name="topic" rows={3} maxLength={2000} className="w-full rounded-lg border border-ink-600 bg-ink-900/80 p-3 text-sm" />
          </label>
          <label className="block md:col-span-2">
            <span className="mb-1.5 block text-sm font-medium text-paper-dim">Audience and instructions (optional)</span>
            <textarea name="instructions" rows={2} maxLength={4000} className="w-full rounded-lg border border-ink-600 bg-ink-900/80 p-3 text-sm" />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-paper-dim">Tone</span>
            <select name="tone" defaultValue={selected.key.includes('paper') || selected.key.includes('academic') ? 'academic' : 'professional'}
              className="h-11 w-full rounded-lg border border-ink-600 bg-ink-900 px-3">
              {TONES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <Field label="Target length (words)" name="word_target" type="number" min={100} max={50000} defaultValue={selected.words} />
          <Field label="Author (optional)" name="author" maxLength={200} />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-paper-dim">Format to a standard</span>
            <select name="standard" className="h-11 w-full rounded-lg border border-ink-600 bg-ink-900 px-3">
              <option value="">House style (Calibri 11, 1-inch margins)</option>
              {stdOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-paper-dim">Citation style</span>
            <select name="citation_style" className="h-11 w-full rounded-lg border border-ink-600 bg-ink-900 px-3">
              <option value="numeric">Numbered [1]</option>
              <option value="author_year">Author–date (Smith, 2020)</option>
            </select>
          </label>
          <label className="block md:col-span-2">
            <span className="mb-1.5 block text-sm font-medium text-paper-dim">References you want to cite (one per line, optional)</span>
            <textarea name="references" rows={4} placeholder="Author, A. (2020). Title. Publisher." className="w-full rounded-lg border border-ink-600 bg-ink-900/80 p-3 font-mono text-xs" />
            <span className="mt-1 block text-xs text-paper-faint">AKSHARA never invents sources. Generated text may cite only these; anything else becomes “[citation needed]”.</span>
          </label>
          {create.isError && <p role="alert" className="text-sm text-sev-critical md:col-span-2">{(create.error as ApiError).message}</p>}
          <div className="md:col-span-2"><Button type="submit" loading={create.isPending}>Create outline</Button></div>
        </form>
      )}
    </div>
  );
}

export function DraftBadge({ origin }: { origin?: string }) {
  if (origin === 'generated') return <Badge tone="gold">AI draft — review</Badge>;
  if (origin === 'edited') return <Badge tone="accent">AI draft, edited</Badge>;
  return null;
}
