import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, json, type StandardDetail, type StandardOut } from '@/api/client';
import BlurText from '@/components/reactbits/BlurText';
import SpotlightCard from '@/components/reactbits/SpotlightCard';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';

function StandardCard({ s }: { s: StandardOut }) {
  const latest = s.versions[s.versions.length - 1];
  return (
    <Link to={`/standards/${latest?.id}`} className="block h-full rounded-2xl">
      <SpotlightCard className="h-full rounded-2xl border border-ink-700 bg-ink-850/80 p-5 hover:border-ink-500" spotlightColor="rgba(245, 196, 107, 0.16)" theme="dark">
        <div className="flex items-start justify-between gap-3">
          <span className="grid size-10 place-items-center rounded-xl border border-gold/30 bg-gold-soft text-gold">
            <Icon name="standard" className="size-5" />
          </span>
          <div className="flex flex-wrap justify-end gap-1">
            {s.builtin ? <Badge tone="gold">Built-in</Badge> : <Badge tone="accent">Custom</Badge>}
            {latest && <Badge tone={latest.status === 'published' ? 'ok' : 'warn'}>{latest.status} v{latest.version}</Badge>}
          </div>
        </div>
        <h3 className="mt-4 font-semibold text-paper">{s.name}</h3>
        <p className="mt-1 line-clamp-2 text-sm text-paper-faint">{s.description || (s.extends ? `Extends ${s.extends}` : 'No description')}</p>
        <p className="mt-3 font-mono text-xs text-paper-faint">{latest?.rule_count ?? 0} own rules{s.extends ? ` + ${s.extends}` : ''}</p>
      </SpotlightCard>
    </Link>
  );
}

export function StandardsPage() {
  const q = useQuery({ queryKey: ['standards'], queryFn: () => api<StandardOut[]>('/standards') });
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: (body: { name: string; description: string; extends: string | null }) =>
      api<StandardDetail>('/standards', { method: 'POST', ...json({ ...body, rules: [] }) }),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ['standards'] });
      navigate(`/standards/${d.version_id}`);
    },
  });
  const builtins = (q.data ?? []).filter((s) => s.builtin);
  const custom = (q.data ?? []).filter((s) => !s.builtin);

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    create.mutate({ name: String(f.get('name')), description: String(f.get('description') ?? ''), extends: String(f.get('extends') || '') || null });
  }

  return (
    <div className="mx-auto max-w-6xl space-y-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="label text-gold/80">Universal Document Standard Engine</p>
          <BlurText text="Standards, as machine-checkable rules." className="mt-2 font-serif text-4xl font-semibold" animateBy="words" delay={60} trigger="load" />
          <p className="mt-2 max-w-2xl text-paper-dim">Hard rules are checked deterministically. Every built-in rule cites its source and how it was verified.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/standards/build" className="inline-flex h-10 items-center gap-2 rounded-lg border border-ink-600 px-4 text-sm font-medium hover:border-ink-500">
            <Icon name="upload" /> Build from guidelines
          </Link>
          <Button onClick={() => setOpen(true)}><Icon name="create" /> New custom standard</Button>
        </div>
      </header>
      <section>
        <h2 className="mb-4 font-serif text-2xl font-semibold">Built-in profiles</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {q.isPending ? <div className="surface h-40 animate-pulse" /> : builtins.map((s) => <StandardCard key={s.slug} s={s} />)}
        </div>
      </section>
      <section>
        <h2 className="mb-4 font-serif text-2xl font-semibold">Your standards</h2>
        {custom.length === 0 ? (
          <div className="surface p-8 text-center text-sm text-paper-faint">
            Create an institutional or corporate standard, optionally extending a built-in profile.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{custom.map((s) => <StandardCard key={s.id} s={s} />)}</div>
        )}
      </section>
      <Dialog open={open} onClose={() => setOpen(false)} title="New custom standard">
        <form onSubmit={onSubmit} className="space-y-4">
          <Field label="Name" name="name" required minLength={2} maxLength={200} placeholder="e.g. Example University Thesis" />
          <Field label="Description (optional)" name="description" maxLength={2000} />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-paper-dim">Start from</span>
            <select name="extends" className="h-11 w-full rounded-lg border border-ink-600 bg-ink-900 px-3 text-paper">
              <option value="">Empty (no base)</option>
              {builtins.map((b) => <option key={b.slug} value={b.slug}>Extend {b.name}</option>)}
            </select>
          </label>
          {create.isError && <p role="alert" className="text-sm text-sev-critical">{(create.error as ApiError).message}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" loading={create.isPending}>Create draft</Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
