import { useMemo, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, json, type FindingOut, type InspectionRun, type VersionOut } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { SEV_ORDER, ScoreRing, SeverityBadge, type Sev } from '@/components/ui/Severity';
import { PageViewer } from '@/features/workspace/PageViewer';
import type { Overlay, PageInfo } from '@/features/workspace/types';
import { downloadFrom } from '@/lib/download';
import { formatDate } from '@/lib/format';

import { FindingCard } from './FindingCard';

export type RunKind = 'inspection' | 'udse' | 'visual';

export function useLatestRun(versionId: string, kind: RunKind, enabled = true) {
  return useQuery({
    queryKey: ['versions', versionId, 'runs', kind],
    queryFn: () => api<InspectionRun | null>(`/versions/${versionId}/inspections/latest?kind=${kind}`),
    enabled,
  });
}

export function DimensionBars({ dims }: { dims: Record<string, number> }) {
  return (
    <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
      {Object.entries(dims).map(([k, v]) => (
        <div key={k}>
          <dt className="label">{k}</dt>
          <dd className="mt-1 flex items-center gap-2">
            <span className="font-mono text-sm tabular-nums">{Math.round(v)}</span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
              <span className={`block h-full rounded-full ${v >= 85 ? 'bg-ok' : v >= 70 ? 'bg-sev-medium' : 'bg-sev-critical'}`} style={{ width: `${v}%` }} />
            </span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function FindingsPanel({
  version,
  kind,
  header,
  rerun,
  empty,
}: {
  version: VersionOut;
  kind: RunKind;
  header?: (run: InspectionRun) => ReactNode;
  rerun?: { label: string; run: () => Promise<unknown> };
  empty?: ReactNode;
}) {
  const qc = useQueryClient();
  const run = useLatestRun(version.id, kind, version.analysis_status === 'complete');
  const pages = useQuery({
    queryKey: ['versions', version.id, 'pages'],
    queryFn: () => api<PageInfo[]>(`/versions/${version.id}/pages`),
    enabled: version.analysis_status === 'complete',
  });
  const [sev, setSev] = useState<Sev | 'all'>('all');
  const [showDismissed, setShowDismissed] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const toggle = useMutation({
    mutationFn: (f: FindingOut) =>
      api<FindingOut>(`/findings/${f.id}`, { method: 'PATCH', ...json({ status: f.status === 'dismissed' ? 'open' : 'dismissed' }) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['versions', version.id, 'runs', kind] }),
  });
  const rerunM = useMutation({
    mutationFn: () => rerun!.run(),
    onSettled: () => void qc.invalidateQueries({ queryKey: ['versions', version.id] }),
  });

  const findings = useMemo(() => run.data?.findings ?? [], [run.data]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of findings) if (f.status !== 'dismissed') c[f.severity] = (c[f.severity] ?? 0) + 1;
    return c;
  }, [findings]);
  const visible = findings.filter((f) => (sev === 'all' || f.severity === sev) && (showDismissed || f.status !== 'dismissed'));
  const overlays: Overlay[] = visible
    .filter((f) => f.page_index !== null && f.bbox && f.bbox.length === 4)
    .map(
      (f): Overlay => ({
        id: f.id,
        page: f.page_index!,
        bbox: [f.bbox![0]!, f.bbox![1]!, f.bbox![2]!, f.bbox![3]!],
        tone: (f.id === activeId ? f.severity : 'info') as Overlay['tone'],
        label: f.message,
      }),
    )
    .filter((o) => activeId === null || o.id === activeId);

  if (version.analysis_status !== 'complete') return <p className="text-sm text-paper-faint">Available once analysis completes.</p>;
  if (run.isPending) return <div className="surface h-64 animate-pulse" />;
  if (!run.data) {
    return (
      <div className="surface flex flex-col items-start gap-3 p-6">
        {empty ?? <p className="text-sm text-paper-dim">No results yet.</p>}
        {rerun && <Button onClick={() => rerunM.mutate()} loading={rerunM.isPending}>{rerun.label}</Button>}
        {rerunM.isError && <p className="text-sm text-sev-critical">{(rerunM.error as Error).message}</p>}
      </div>
    );
  }

  const r = run.data;
  const scores = (r.stats.scores ?? {}) as { overall?: number; dimensions?: Record<string, number> };
  const skipped = (r.stats.not_evaluated ?? []) as { check?: string; rule?: string; reason: string }[];
  const select = (f: FindingOut) => {
    setActiveId(f.id === activeId ? null : f.id);
    if (f.page_index !== null) setPage(f.page_index);
  };

  return (
    <div className="space-y-6">
      <section className="surface flex flex-wrap items-center gap-6 p-5">
        {header ? header(r) : (
          <>
            <ScoreRing value={scores.overall} label="Quality score" />
            {scores.dimensions && <DimensionBars dims={scores.dimensions} />}
          </>
        )}
        <div className="flex w-full flex-wrap items-center justify-between gap-3 border-t border-ink-700 pt-4 text-xs text-paper-faint">
          <span>
            Checked {formatDate(r.created_at)} · {r.engine_version}
            {skipped.length > 0 && ` · ${skipped.length} not evaluated`}
          </span>
          <span className="flex flex-wrap gap-2">
            {rerun && (
              <Button size="sm" variant="secondary" loading={rerunM.isPending} onClick={() => rerunM.mutate()}>
                <Icon name="history" /> {rerun.label}
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={() => void downloadFrom(`/inspections/${r.id}/report?format=pdf`, `akshara-${kind}-report.pdf`)}>
              <Icon name="download" /> PDF report
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void downloadFrom(`/inspections/${r.id}/report?format=json`, `akshara-${kind}-report.json`)}>
              JSON
            </Button>
          </span>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <section aria-label="Findings" className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by severity">
            <button type="button" onClick={() => setSev('all')} aria-pressed={sev === 'all'}
              className={`rounded-full border px-3 py-1 text-xs ${sev === 'all' ? 'border-accent bg-accent-soft text-paper' : 'border-ink-600 text-paper-faint'}`}>
              All {findings.filter((f) => f.status !== 'dismissed').length}
            </button>
            {SEV_ORDER.filter((s) => counts[s]).map((s) => (
              <button key={s} type="button" onClick={() => setSev(s)} aria-pressed={sev === s}
                className={`rounded-full ${sev === s ? 'ring-2 ring-accent' : ''}`}>
                <span className="inline-flex items-center gap-1"><SeverityBadge severity={s} /><span className="sr-only">count</span></span>
                <span className="ml-1 font-mono text-xs text-paper-dim">{counts[s]}</span>
              </button>
            ))}
            <label className="ml-auto flex items-center gap-1.5 text-xs text-paper-faint">
              <input type="checkbox" checked={showDismissed} onChange={(e) => setShowDismissed(e.target.checked)} className="accent-[#8b93ff]" />
              Show dismissed
            </label>
          </div>
          {visible.length === 0 ? (
            <div className="surface p-6 text-center">
              <p className="font-serif text-lg">{findings.length === 0 ? 'No issues found' : 'Nothing matches this filter'}</p>
              {findings.length === 0 && <p className="mt-1 text-sm text-paper-faint">Every check that could run passed.</p>}
            </div>
          ) : (
            <ul className="max-h-[70vh] space-y-2 overflow-y-auto pr-1">
              {visible.map((f) => (
                <FindingCard key={f.id} finding={f} active={f.id === activeId} onSelect={() => select(f)} onToggleDismiss={() => toggle.mutate(f)} />
              ))}
            </ul>
          )}
          {skipped.length > 0 && (
            <details className="mt-4 text-xs text-paper-faint">
              <summary className="cursor-pointer">Checks not evaluated ({skipped.length})</summary>
              <ul className="mt-2 space-y-1">
                {skipped.map((s) => (
                  <li key={(s.check ?? s.rule) + s.reason}><span className="font-mono">{s.check ?? s.rule}</span>: {s.reason}</li>
                ))}
              </ul>
            </details>
          )}
        </section>
        <section aria-label="Located on page" className="min-w-0">
          {pages.data && pages.data.length > 0 ? (
            <PageViewer versionId={version.id} pages={pages.data} overlays={overlays} page={page} onPageChange={setPage} />
          ) : (
            <p className="text-sm text-paper-faint">No rendered pages to show findings on.</p>
          )}
        </section>
      </div>
    </div>
  );
}
