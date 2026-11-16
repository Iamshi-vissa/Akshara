import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { useMutation, useQuery } from '@tanstack/react-query';

import { api, ApiError, json, type DocumentPage, type ThemeOut } from '@/api/client';
import { runJob } from '@/api/jobs';
import { useCapabilities } from '@/components/layout/AppShell';
import BlurText from '@/components/reactbits/BlurText';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';

type Source = 'document' | 'outline' | 'brief';

const SOURCES: { key: Source; label: string; hint: string }[] = [
  { key: 'document', label: 'From a document', hint: 'One slide per section, key sentences as bullets, the section text as speaker notes.' },
  { key: 'outline', label: 'From an outline', hint: 'Write “# Slide title”, “- bullet”, “> speaker note”, “## Section divider”.' },
  { key: 'brief', label: 'From a brief (AI)', hint: 'The assistant plans the slides from your description. Review every slide.' },
];

const SAMPLE = `# Project update
> Thank everyone for coming.
# Where we are
- Prototype finished and tested with five users
- Two issues found in the export step
> Mention the fix dates.
## Next steps
# Plan for next month
- Fix the export issues
- Run a second round of testing`;

export function PresentationsPage() {
  const navigate = useNavigate();
  const caps = useCapabilities();
  const ai = caps.data?.capabilities.find((c) => c.key === 'ai_generate');
  const themes = useQuery({ queryKey: ['presentations', 'themes'], queryFn: () => api<ThemeOut[]>('/presentations/themes') });
  const docs = useQuery({ queryKey: ['documents', 'list', { kind: 'all-src' }], queryFn: () => api<DocumentPage>('/documents?limit=100') });
  const [source, setSource] = useState<Source>('document');
  const [theme, setTheme] = useState('paper');
  const make = useMutation({
    mutationFn: (body: Record<string, unknown>) => runJob('/presentations', json(body)),
    onSuccess: (job) => navigate(`/documents/${String((job.result as { document_id: string }).document_id)}`),
  });
  const sources = (docs.data?.items ?? []).filter((d) => d.current_version && d.kind !== 'pptx');

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body: Record<string, unknown> = { source, theme, title: f.get('title') ?? '' };
    if (source === 'document') body.version_id = f.get('version_id');
    if (source === 'outline') body.outline = f.get('outline');
    if (source === 'brief') Object.assign(body, { brief: f.get('brief'), audience: f.get('audience'), slide_count: Number(f.get('slide_count')) || 10 });
    make.mutate(body);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header>
        <p className="label text-gold/80">Generate presentation</p>
        <BlurText text="Slides that fit, every time." className="mt-2 font-serif text-4xl font-semibold" animateBy="words" delay={60} trigger="load" />
        <p className="mt-2 max-w-2xl text-paper-dim">
          Text is sized from a fixed scale with an 18 pt minimum; anything that does not fit moves to a continuation slide.
          Every deck has slide numbers and speaker notes, and is inspected as soon as it is created.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-6" aria-label="New presentation">
        <fieldset className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-3 font-serif text-xl font-semibold">1. Source</legend>
          {SOURCES.map((s) => {
            const disabled = s.key === 'brief' && !ai?.available;
            return (
              <label key={s.key} className={`surface cursor-pointer p-4 transition-colors ${source === s.key ? 'border-accent bg-accent-soft' : 'hover:border-ink-500'} ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}>
                <input type="radio" name="source" value={s.key} checked={source === s.key} disabled={disabled} onChange={() => setSource(s.key)} className="sr-only" />
                <span className="font-medium">{s.label}</span>
                <span className="mt-1 block text-xs text-paper-faint">{disabled ? `Unavailable: ${ai?.note ?? ''}` : s.hint}</span>
              </label>
            );
          })}
        </fieldset>

        <section className="surface grid gap-5 p-6" aria-label="Content">
          <h2 className="font-serif text-xl font-semibold">2. Content</h2>
          <Field label="Deck title (optional)" name="title" maxLength={300} />
          {source === 'document' && (
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-paper-dim">Document</span>
              <select name="version_id" required className="h-11 w-full rounded-lg border border-ink-600 bg-ink-900 px-3">
                {sources.length === 0 && <option value="">No DOCX or PDF documents yet — upload one first</option>}
                {sources.map((d) => <option key={d.id} value={d.current_version!.id}>{d.title} ({d.kind.toUpperCase()})</option>)}
              </select>
            </label>
          )}
          {source === 'outline' && (
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-paper-dim">Outline</span>
              <textarea name="outline" required rows={12} defaultValue={SAMPLE} maxLength={50000} className="w-full rounded-lg border border-ink-600 bg-ink-900/80 p-3 font-mono text-xs" />
            </label>
          )}
          {source === 'brief' && (
            <>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-paper-dim">What is the talk about?</span>
                <textarea name="brief" required minLength={20} rows={5} maxLength={8000} className="w-full rounded-lg border border-ink-600 bg-ink-900/80 p-3 text-sm" />
                <span className="mt-1 block text-xs text-paper-faint">The assistant will not invent facts or sources; gaps are flagged in the speaker notes.</span>
              </label>
              <div className="grid gap-5 md:grid-cols-2">
                <Field label="Audience (optional)" name="audience" maxLength={500} />
                <Field label="About how many slides?" name="slide_count" type="number" min={3} max={30} defaultValue={10} />
              </div>
            </>
          )}
        </section>

        <fieldset aria-label="Theme">
          <legend className="mb-3 font-serif text-xl font-semibold">3. Theme</legend>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(themes.data ?? []).map((t) => (
              <label key={t.key} className={`cursor-pointer rounded-2xl border p-2 transition-colors ${theme === t.key ? 'border-accent' : 'border-ink-700 hover:border-ink-500'}`}>
                <input type="radio" name="theme" value={t.key} checked={theme === t.key} onChange={() => setTheme(t.key)} className="sr-only" />
                <div className="aspect-video rounded-lg p-3" style={{ background: `#${t.background}` }} aria-hidden>
                  <div className="h-2.5 w-3/4 rounded-sm" style={{ background: `#${t.title}` }} />
                  <div className="mt-1.5 h-1 w-6 rounded-sm" style={{ background: `#${t.accent}` }} />
                  <div className="mt-3 space-y-1">
                    {[80, 65, 72].map((w) => <div key={w} className="h-1.5 rounded-sm opacity-50" style={{ width: `${w}%`, background: `#${t.title}` }} />)}
                  </div>
                </div>
                <p className="mt-2 px-1 text-sm">{t.label}</p>
              </label>
            ))}
          </div>
        </fieldset>

        {make.isError && <p role="alert" className="text-sm text-sev-critical">{(make.error as ApiError).message}</p>}
        <Button type="submit" loading={make.isPending} disabled={source === 'document' && sources.length === 0}>
          Generate presentation
        </Button>
      </form>
    </div>
  );
}
