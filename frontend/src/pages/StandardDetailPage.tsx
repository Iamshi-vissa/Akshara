import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, json, type StandardDetail } from '@/api/client';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { SeverityBadge } from '@/components/ui/Severity';
import { describeCheck, VERIFICATION_LABEL, type UdseRule } from '@/features/standards/rules';

const CATEGORY_ORDER = ['page', 'typography', 'structure', 'references', 'figures_tables', 'layout', 'slides'];

function marginRules(v: number): UdseRule[] {
  return (['top', 'bottom', 'left', 'right'] as const).map((side) => ({
    id: `page.margin.${side}`, title: `${side[0]!.toUpperCase()}${side.slice(1)} margin`, category: 'page', kind: 'hard', severity: 'high',
    selector: { node: 'page_setup' }, check: { op: 'equals', property: `margins.${side}`, value: v, unit: 'in', tolerance: 0.05 },
    fix: { strategy: 'set_margins', auto: true },
  }));
}

/** Templates for the most common institutional requirements; values are entered by the user. */
const TEMPLATES: Record<string, { label: string; build: (v: string) => UdseRule[] }> = {
  margin: {
    label: 'All margins (inches)',
    build: (v) => marginRules(Number(v)),
  },
  font: {
    label: 'Body font family',
    build: (v) => [{ id: 'typography.body_font', title: 'Body font', category: 'typography', kind: 'hard', severity: 'medium',
      selector: { node: 'body_paragraph' }, check: { op: 'in_set', property: 'font_family', values: v.split(',').map((x) => x.trim()).filter(Boolean) },
      fix: { strategy: 'set_body_font', auto: true } }],
  },
  size: {
    label: 'Body font size (pt)',
    build: (v) => [{ id: 'typography.body_size', title: 'Body font size', category: 'typography', kind: 'hard', severity: 'medium',
      selector: { node: 'body_paragraph' }, check: { op: 'equals', property: 'size_pt', value: Number(v), unit: 'pt', tolerance: 0.25 },
      fix: { strategy: 'set_body_font', auto: true } }],
  },
  spacing: {
    label: 'Line spacing (1, 1.5, 2)',
    build: (v) => [{ id: 'typography.line_spacing', title: 'Line spacing', category: 'typography', kind: 'hard', severity: 'high',
      applies_to: ['docx'], selector: { node: 'body_paragraph' }, check: { op: 'equals', property: 'line_spacing', value: Number(v), tolerance: 0.05 },
      fix: { strategy: 'set_line_spacing', auto: true } }],
  },
  abstract: {
    label: 'Abstract word limit',
    build: (v) => [{ id: 'structure.abstract_length', title: 'Abstract length', category: 'structure', kind: 'soft', severity: 'low',
      selector: { node: 'section', where: { role: 'abstract' } }, check: { op: 'max_words', max: Number(v) } }],
  },
};


function RuleRow({ rule, inherited, onRemove }: { rule: UdseRule; inherited: boolean; onRemove?: () => void }) {
  const [open, setOpen] = useState(false);
  const v = rule.provenance ? VERIFICATION_LABEL[rule.provenance.verification] : undefined;
  return (
    <li className="px-5 py-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setOpen((o) => !o)} className="min-w-0 flex-1 text-left" aria-expanded={open}>
          <span className="font-medium text-paper">{rule.title}</span>
          <span className="ml-2 font-mono text-xs text-paper-faint">{rule.id}</span>
          <p className="mt-0.5 font-mono text-xs text-accent-strong/90">{describeCheck(rule)}</p>
        </button>
        <span className={`rounded border px-1.5 font-mono text-[10px] uppercase ${rule.kind === 'hard' ? 'border-accent/40 text-accent-strong' : 'border-ink-600 text-paper-faint'}`}>{rule.kind}</span>
        <SeverityBadge severity={rule.severity} />
        {v && <Badge tone={v.tone}>{v.label}</Badge>}
        {inherited && <Badge>inherited</Badge>}
        {onRemove && (
          <button type="button" onClick={onRemove} className="text-paper-faint hover:text-sev-critical" aria-label={`Remove rule ${rule.id}`}>
            <Icon name="trash" />
          </button>
        )}
      </div>
      {open && rule.provenance && (
        <div className="mt-3 space-y-1 rounded-lg border border-ink-700 bg-ink-900/60 p-3 text-xs text-paper-dim">
          <p><span className="text-paper-faint">Source:</span> {rule.provenance.source}{rule.provenance.locator ? ` — ${rule.provenance.locator}` : ''}</p>
          {rule.provenance.quote && <blockquote className="border-l-2 border-gold/40 pl-2 italic">“{rule.provenance.quote}”</blockquote>}
          {rule.provenance.notes && <p>{rule.provenance.notes}</p>}
          {rule.fix?.hint && <p className="text-ok/90">Fix: {rule.fix.hint}</p>}
        </div>
      )}
    </li>
  );
}

export function StandardDetailPage() {
  const { versionId = '' } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ['standard-version', versionId], queryFn: () => api<StandardDetail>(`/standard-versions/${versionId}`) });
  const [error, setError] = useState<string | null>(null);
  const [jsonText, setJsonText] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (rules: UdseRule[]) => api<StandardDetail>(`/standard-versions/${versionId}/rules`, { method: 'PUT', ...json({ rules }) }),
    onSuccess: (d) => {
      qc.setQueryData(['standard-version', versionId], d);
      setError(null);
      setJsonText(null);
    },
    onError: (e) => {
      const err = e as ApiError;
      const details = (err.details?.errors as { loc: unknown[]; msg: string }[] | undefined)?.map((x) => `${x.loc.join('.')}: ${x.msg}`) ?? [];
      setError([err.message, ...details].join('\n'));
    },
  });
  const publish = useMutation({
    mutationFn: () => api<StandardDetail>(`/standard-versions/${versionId}/publish`, { method: 'POST' }),
    onSuccess: (d) => {
      qc.setQueryData(['standard-version', versionId], d);
      void qc.invalidateQueries({ queryKey: ['standards'] });
    },
    onError: (e) => setError((e as Error).message),
  });
  const newDraft = useMutation({
    mutationFn: (standardId: string) => api<StandardDetail>(`/standards/${standardId}/versions`, { method: 'POST' }),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ['standards'] });
      navigate(`/standards/${d.version_id}`);
    },
  });

  const d = q.data;
  const own = useMemo(() => (d?.own_rules ?? []) as unknown as UdseRule[], [d]);
  const ownIds = new Set(own.map((r) => r.id));
  const rules = (d?.rules ?? []) as unknown as UdseRule[];
  const grouped = CATEGORY_ORDER.map((c) => [c, rules.filter((r) => r.category === c)] as const).filter(([, rs]) => rs.length);
  const editable = d && !d.builtin && d.status === 'draft';

  function addTemplate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const key = String(f.get('template'));
    const value = String(f.get('value') ?? '').trim();
    if (!value) return;
    const added = TEMPLATES[key]!.build(value);
    const merged = [...own.filter((r) => !added.some((a) => a.id === r.id)), ...added];
    save.mutate(merged);
    e.currentTarget.reset();
  }

  if (q.isPending) return <div className="surface mx-auto h-96 max-w-5xl animate-pulse" />;
  if (q.isError || !d) return <p className="text-sev-critical">Standard not found.</p>;

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <Link to="/standards" className="inline-flex items-center gap-2 text-sm text-paper-faint hover:text-paper"><Icon name="back" /> Standards</Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex flex-wrap gap-2">
            {d.builtin ? <Badge tone="gold">Built-in</Badge> : <Badge tone="accent">Custom</Badge>}
            <Badge tone={d.status === 'published' ? 'ok' : 'warn'}>{d.status} · v{d.version}</Badge>
            {d.extends && <Badge>extends {d.extends}</Badge>}
          </div>
          <h1 className="font-serif text-4xl font-semibold">{d.name}</h1>
          {d.description && <p className="mt-2 max-w-3xl text-paper-dim">{d.description}</p>}
          {d.notice && <p className="mt-3 max-w-3xl rounded-lg border border-gold/25 bg-gold-soft px-3 py-2 text-sm text-gold">{d.notice}</p>}
        </div>
        <div className="flex gap-2">
          {editable && <Button loading={publish.isPending} onClick={() => publish.mutate()}>Publish version</Button>}
          {!d.builtin && d.status === 'published' && d.standard_id && (
            <Button variant="secondary" loading={newDraft.isPending} onClick={() => newDraft.mutate(d.standard_id!)}>Create new draft</Button>
          )}
        </div>
      </header>

      {error && <pre role="alert" className="rounded-lg border border-sev-critical/30 bg-sev-critical/10 p-3 text-xs whitespace-pre-wrap text-sev-critical">{error}</pre>}

      {editable && (
        <section className="surface space-y-4 p-5" aria-label="Add rules">
          <h2 className="font-serif text-xl font-semibold">Add a requirement</h2>
          <form onSubmit={addTemplate} className="flex flex-wrap items-end gap-3">
            <label className="block">
              <span className="mb-1 block text-xs text-paper-faint">Requirement</span>
              <select name="template" className="h-10 rounded-lg border border-ink-600 bg-ink-900 px-3 text-sm">
                {Object.entries(TEMPLATES).map(([k, t]) => <option key={k} value={k}>{t.label}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-paper-faint">Value</span>
              <input name="value" required className="h-10 w-48 rounded-lg border border-ink-600 bg-ink-900 px-3 text-sm" placeholder="e.g. 1.25 or Arial, Calibri" />
            </label>
            <Button type="submit" loading={save.isPending}>Add</Button>
          </form>
          <details onToggle={(e) => (e.currentTarget.open ? setJsonText(JSON.stringify(own, null, 2)) : setJsonText(null))}>
            <summary className="cursor-pointer text-sm text-paper-faint">Advanced: edit this version's own rules as JSON</summary>
            {jsonText !== null && (
              <div className="mt-3 space-y-2">
                <textarea value={jsonText} onChange={(e) => setJsonText(e.target.value)} rows={14} spellCheck={false}
                  aria-label="Rules JSON" className="w-full rounded-lg border border-ink-600 bg-ink-950 p-3 font-mono text-xs text-paper" />
                <Button size="sm" onClick={() => {
                  try {
                    save.mutate(JSON.parse(jsonText) as UdseRule[]);
                  } catch {
                    setError('The JSON is not valid.');
                  }
                }}>Validate &amp; save</Button>
              </div>
            )}
          </details>
        </section>
      )}

      <section aria-label="Rules" className="space-y-6">
        <p className="text-sm text-paper-faint">{rules.length} effective rules · {rules.filter((r) => r.kind === 'hard').length} hard, {rules.filter((r) => r.kind === 'soft').length} soft</p>
        {grouped.map(([cat, rs]) => (
          <div key={cat}>
            <h3 className="label mb-2">{cat.replace('_', ' & ')}</h3>
            <ul className="surface divide-y divide-ink-700/70">
              {rs.map((r) => (
                <RuleRow key={r.id} rule={r} inherited={!d.builtin && !ownIds.has(r.id)}
                  onRemove={editable && ownIds.has(r.id) ? () => save.mutate(own.filter((x) => x.id !== r.id)) : undefined} />
              ))}
            </ul>
          </div>
        ))}
        {rules.length === 0 && <div className="surface p-8 text-center text-sm text-paper-faint">No rules yet. Add a requirement above.</div>}
      </section>
    </div>
  );
}
