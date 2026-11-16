import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, json, type ChangeSetOut, type DocumentOut, type JobOut, type VersionOut } from '@/api/client';
import { runJob } from '@/api/jobs';
import { useCapabilities } from '@/components/layout/AppShell';
import StatusMark from '@/components/reactbits/StatusMark';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { relativeTime } from '@/lib/format';

import { ProposalCard } from './ProposalCard';

type Decision = 'accepted' | 'rejected' | 'pending';
type Step = Record<string, Decision>; // proposal id -> decision, one user action

const SOURCE_LABEL: Record<string, string> = {
  autocorrect: 'Automatic corrections',
  grammar: 'Grammar & spelling',
  ai_edit: 'AI suggestions',
  manual: 'Your edits',
};

function Score({ label, before, after }: { label: string; before?: number | null; after?: number | null }) {
  if (before == null && after == null) return null;
  const up = (after ?? 0) >= (before ?? 0);
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-900/60 px-4 py-3">
      <p className="label">{label}</p>
      <p className="mt-1 font-serif text-2xl tabular-nums">
        <span className="text-paper-faint">{before ?? '—'}</span>
        <span className="mx-2 text-paper-faint">→</span>
        <span className={up ? 'text-ok' : 'text-sev-critical'}>{after ?? '—'}</span>
      </p>
    </div>
  );
}

export function ChangesPanel({ doc, version, onOpenVersion }: { doc: DocumentOut; version: VersionOut; onOpenVersion?: () => void }) {
  const qc = useQueryClient();
  const caps = useCapabilities();
  const grammar = caps.data?.capabilities.find((c) => c.key === 'grammar');
  const list = useQuery({
    queryKey: ['documents', doc.id, 'changesets'],
    queryFn: () => api<ChangeSetOut[]>(`/documents/${doc.id}/changesets`),
  });
  const openId = list.data?.find((c) => c.status === 'open' && c.base_version_id === version.id)?.id ?? null;
  const [selected, setSelected] = useState<string | null>(null);
  const activeId = selected ?? openId;
  const cs = useQuery({
    queryKey: ['changesets', activeId],
    queryFn: () => api<ChangeSetOut>(`/changesets/${activeId}`),
    enabled: !!activeId,
  });
  const [undo, setUndo] = useState<Step[]>([]);
  const [redo, setRedo] = useState<Step[]>([]);
  const [result, setResult] = useState<JobOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['documents', doc.id] });
    void qc.invalidateQueries({ queryKey: ['versions'] });
  };
  const create = useMutation({
    mutationFn: (source: 'autocorrect' | 'grammar') =>
      api<ChangeSetOut>(`/documents/${doc.id}/changesets`, { method: 'POST', ...json({ source }) }),
    onSuccess: (c) => {
      setSelected(c.id);
      setUndo([]);
      setRedo([]);
      setResult(null);
      setError(null);
      qc.setQueryData(['changesets', c.id], c);
      void qc.invalidateQueries({ queryKey: ['documents', doc.id, 'changesets'] });
    },
    onError: (e) => setError((e as ApiError).message),
  });
  const decide = useMutation({
    mutationFn: (step: Step) => api<ChangeSetOut>(`/changesets/${activeId}/decisions`, { method: 'POST', ...json({ decisions: step }) }),
    onSuccess: (c) => qc.setQueryData(['changesets', c.id], c),
  });
  const apply = useMutation({
    mutationFn: () => runJob(`/changesets/${activeId}/apply`),
    onSuccess: (job) => {
      setResult(job);
      refresh();
      void qc.invalidateQueries({ queryKey: ['changesets', activeId] });
      void qc.invalidateQueries({ queryKey: ['documents', doc.id, 'changesets'] });
    },
    onError: (e) => setError((e as Error).message),
  });

  const data = cs.data;
  const proposals = data?.proposals ?? [];
  const editable = data?.status === 'open';

  /** Record a user action so it can be undone; `inverse` restores the previous decisions. */
  function act(step: Step) {
    const inverse: Step = {};
    for (const id of Object.keys(step)) inverse[id] = (proposals.find((p) => p.id === id)?.decision ?? 'pending') as Decision;
    setUndo((u) => [...u, inverse]);
    setRedo([]);
    decide.mutate(step);
  }
  function undoLast() {
    const last = undo[undo.length - 1];
    if (!last) return;
    const forward: Step = {};
    for (const id of Object.keys(last)) forward[id] = (proposals.find((p) => p.id === id)?.decision ?? 'pending') as Decision;
    setUndo((u) => u.slice(0, -1));
    setRedo((r) => [...r, forward]);
    decide.mutate(last);
  }
  function redoLast() {
    const next = redo[redo.length - 1];
    if (!next) return;
    const inverse: Step = {};
    for (const id of Object.keys(next)) inverse[id] = (proposals.find((p) => p.id === id)?.decision ?? 'pending') as Decision;
    setRedo((r) => r.slice(0, -1));
    setUndo((u) => [...u, inverse]);
    decide.mutate(next);
  }

  const accepted = proposals.filter((p) => p.decision === 'accepted').length;
  const res = result?.result as { before?: Record<string, number>; after?: Record<string, number> } | undefined;

  return (
    <div className="space-y-6">
      <section className="surface flex flex-wrap items-center gap-3 p-4">
        <Button onClick={() => create.mutate('autocorrect')} loading={create.isPending && create.variables === 'autocorrect'} disabled={doc.kind === 'pdf'}>
          <Icon name="check" /> Propose fixes for findings
        </Button>
        <Button variant="secondary" onClick={() => create.mutate('grammar')} disabled={!grammar?.available}
          loading={create.isPending && create.variables === 'grammar'} title={grammar?.available ? undefined : grammar?.note}>
          Check grammar &amp; spelling
        </Button>
        {!grammar?.available && grammar && <span className="text-xs text-paper-faint">Grammar: {grammar.note}</span>}
        {doc.kind === 'pdf' && (
          <p className="w-full text-sm text-paper-dim">PDFs cannot be corrected in place. AKSHARA reports the issues; fix them in the source file and upload it as a new document.</p>
        )}
        {error && <p role="alert" className="w-full text-sm text-sev-critical">{error}</p>}
      </section>

      {result && (
        <section className="rounded-2xl border border-ok/30 bg-ok/5 p-5" role="status">
          <div className="flex items-center gap-3">
            <StatusMark status="done" size={22} doneColor="#4ade80" />
            <p className="font-semibold">Applied. A new version was created and re-checked; the previous version is unchanged.</p>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Score label="Quality score" before={res?.before?.inspection} after={res?.after?.inspection} />
            <Score label="Compliance score" before={res?.before?.udse} after={res?.after?.udse} />
          </div>
          {onOpenVersion && <Button className="mt-4" variant="secondary" size="sm" onClick={onOpenVersion}>View the new version</Button>}
        </section>
      )}

      {activeId && data ? (
        <section className="space-y-4" aria-label="Proposals">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="font-serif text-2xl font-semibold">{SOURCE_LABEL[data.source] ?? data.source}</h2>
            <Badge tone={data.status === 'open' ? 'accent' : data.status === 'applied' ? 'ok' : 'warn'}>{data.status}</Badge>
            <span className="text-xs text-paper-faint">{proposals.length} proposals · created {relativeTime(data.created_at)}</span>
            {Number(data.summary.manual_only) > 0 && (
              <span className="text-xs text-sev-medium">{String(data.summary.manual_only)} issue(s) need a manual fix</span>
            )}
          </div>
          {editable && (
            <div className="surface flex flex-wrap items-center gap-2 p-3">
              <Button size="sm" variant="secondary" onClick={() => act(Object.fromEntries(proposals.filter((p) => p.risk === 'formatting_only').map((p) => [p.id, 'accepted' as Decision])))}>
                Accept all formatting-only
              </Button>
              <Button size="sm" variant="ghost" onClick={() => act(Object.fromEntries(proposals.map((p) => [p.id, 'rejected' as Decision])))}>Reject all</Button>
              <Button size="sm" variant="ghost" disabled={!undo.length} onClick={undoLast} aria-label="Undo last decision">↶ Undo</Button>
              <Button size="sm" variant="ghost" disabled={!redo.length} onClick={redoLast} aria-label="Redo">↷ Redo</Button>
              <span className="ml-auto text-sm text-paper-dim">{accepted} accepted</span>
              <Button disabled={!accepted} loading={apply.isPending} onClick={() => apply.mutate()}>
                Apply {accepted || ''} accepted change{accepted === 1 ? '' : 's'}
              </Button>
            </div>
          )}
          {data.status === 'stale' && <p className="text-sm text-sev-medium">The document changed after these proposals were made. Create new proposals.</p>}
          {data.error_message && <p className="text-sm text-sev-critical">{data.error_message}</p>}
          <ul className="space-y-3">
            {proposals.map((p) => (
              <ProposalCard key={p.id} p={p} disabled={!editable || decide.isPending} onDecide={(d) => act({ [p.id]: d })} />
            ))}
          </ul>
        </section>
      ) : (
        <div className="surface p-8 text-center text-sm text-paper-faint">
          No open proposals. Generate fixes from the inspection and compliance findings, check grammar, or edit text in the Edit tab.
        </div>
      )}

      {(list.data ?? []).length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-paper-dim">Change history ({list.data!.length})</summary>
          <ul className="mt-2 divide-y divide-ink-700/60 rounded-lg border border-ink-700">
            {list.data!.map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => setSelected(c.id)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-ink-800">
                  <span className="flex-1">{SOURCE_LABEL[c.source] ?? c.source}</span>
                  <Badge tone={c.status === 'applied' ? 'ok' : c.status === 'open' ? 'accent' : 'neutral'}>{c.status}</Badge>
                  <span className="text-xs text-paper-faint">{relativeTime(c.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
