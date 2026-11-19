import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { api, type FindingOut, type VersionOut } from '@/api/client';
import { ScoreRing, SeverityBadge } from '@/components/ui/Severity';
import { useLatestRun } from '@/features/inspection/FindingsPanel';
import { PageViewer } from '@/features/workspace/PageViewer';
import type { Overlay, PageInfo } from '@/features/workspace/types';

const CHECKS: Record<string, string> = {
  'VIS.CONTENT_OFF_PAGE': 'Cut off at the page edge',
  'VIS.MARGIN_INTRUSION': 'Into the margin',
  'VIS.BLANK_PAGE': 'Blank page',
  'VIS.SPARSE_PAGE': 'Nearly empty page',
  'VIS.TEXT_OVERLAP': 'Overlapping text',
  'VIS.LOW_CONTRAST': 'Low contrast',
  'VIS.ALIGNMENT': 'Off the text edge',
};

type Boxes = { boxes?: number[][] };

/** Render-based quality: every defect is drawn on the page where it occurs. */
export function VisualPanel({ version, unit }: { version: VersionOut; unit: 'Page' | 'Slide' }) {
  const ready = version.analysis_status === 'complete';
  const run = useLatestRun(version.id, 'inspection', ready);
  const pages = useQuery({
    queryKey: ['versions', version.id, 'pages'],
    queryFn: () => api<PageInfo[]>(`/versions/${version.id}/pages`),
    enabled: ready,
  });
  const [page, setPage] = useState(0);
  const [active, setActive] = useState<string | null>(null);

  const findings = useMemo(
    () => (run.data?.findings ?? []).filter((f) => f.category === 'visual' && f.status !== 'dismissed'),
    [run.data],
  );
  const overlays: Overlay[] = findings
    .filter((f) => f.page_index !== null && (active === null || f.id === active))
    .flatMap((f) => {
      const boxes = ((f.actual as Boxes | null)?.boxes ?? (f.bbox ? [f.bbox] : [])).filter((b) => b.length === 4);
      return boxes.map((b, i): Overlay => ({
        id: `${f.id}:${i}`,
        page: f.page_index!,
        bbox: [b[0]!, b[1]!, b[2]!, b[3]!],
        tone: f.severity as Overlay['tone'],
        label: f.message,
      }));
    });

  if (!ready) return <p className="text-sm text-paper-faint">Available once analysis completes.</p>;
  if (run.isPending || pages.isPending) return <div className="surface h-64 animate-pulse" />;
  if (!run.data) return <p className="text-sm text-paper-dim">This version has not been inspected yet.</p>;

  const scores = (run.data.stats.scores ?? {}) as { dimensions?: Record<string, number> };
  const score = scores.dimensions?.visual;
  const skipped = ((run.data.stats.not_evaluated ?? []) as { check?: string; reason: string }[]).filter((s) => s.check?.startsWith('VIS.'));
  const byCheck = Object.keys(CHECKS).map((code) => ({ code, n: findings.filter((f) => f.code === code).length }));
  const select = (f: FindingOut) => {
    setActive(f.id === active ? null : f.id);
    if (f.page_index !== null) setPage(f.page_index);
  };

  return (
    <div className="space-y-6">
      <section className="surface flex flex-wrap items-center gap-6 p-5" aria-label="Visual score">
        {score !== undefined && <ScoreRing value={score} label="Visual" />}
        <div className="min-w-0 flex-1">
          <p className="text-sm text-paper-dim">
            Checked on the rendered {unit.toLowerCase()}s: content cut off or pushed into margins, blank and nearly empty
            {unit === 'Slide' ? ' slides' : ' pages'}, overlapping text, contrast (WCAG AA) and alignment.
          </p>
          <ul className="mt-3 flex flex-wrap gap-2 text-xs">
            {byCheck.map(({ code, n }) => (
              <li key={code} className={`rounded-full border px-2.5 py-1 ${n ? 'border-sev-medium/40 text-paper' : 'border-ink-700 text-paper-faint'}`}>
                {CHECKS[code]} <span className="font-mono">{n ? n : '✓'}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {skipped.length > 0 && (
        <p className="text-xs text-paper-faint">
          Not evaluated: {skipped.map((s) => `${CHECKS[s.check ?? ''] ?? s.check} (${s.reason})`).join('; ')}
        </p>
      )}

      <div className="grid gap-6 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <ul className="space-y-2" aria-label="Visual findings">
          {findings.length === 0 && <li className="surface p-4 text-sm text-paper-dim">No visual defects found.</li>}
          {findings.map((f) => (
            <li key={f.id}>
              <button
                type="button"
                onClick={() => select(f)}
                aria-pressed={f.id === active}
                className={`surface w-full p-4 text-left transition-colors ${f.id === active ? 'border-accent' : 'hover:border-ink-500'}`}
              >
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={f.severity} />
                  <span className="text-xs text-paper-faint">{f.location}</span>
                </div>
                <p className="mt-2 text-sm">{f.message}</p>
                <p className="mt-1 text-xs text-paper-faint">{f.recommendation}</p>
              </button>
            </li>
          ))}
        </ul>
        <PageViewer versionId={version.id} pages={pages.data ?? []} overlays={overlays} page={page} onPageChange={setPage} unit={unit} />
      </div>
    </div>
  );
}
