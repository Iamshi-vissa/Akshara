import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { api, type VersionOut } from '@/api/client';
import StatusMark from '@/components/reactbits/StatusMark';
import { Badge } from '@/components/ui/Badge';

import { PageViewer } from './PageViewer';
import { StructureTree } from './StructureTree';
import type { OutlineNode, Overlay, PageInfo } from './types';

type Summary = Record<string, unknown>;

export function AnalysisStatus({ version }: { version: VersionOut }) {
  const s = version.analysis_status;
  if (s === 'complete') return null;
  const running = s === 'pending' || s === 'processing';
  return (
    <div className="surface flex items-center gap-4 px-5 py-4" role="status">
      <StatusMark status={running ? 'running' : 'failed'} size={22} color="#8b93ff" errorColor="#f87171" />
      <div>
        <p className="text-sm font-medium">{running ? 'Analysing document…' : 'Analysis failed'}</p>
        <p className="text-xs text-paper-faint">
          {running ? 'Reading structure and rendering pages. This usually takes a few seconds.' : version.analysis_error}
        </p>
      </div>
    </div>
  );
}

export function SummaryStats({ summary, kind }: { summary: Summary; kind: string }) {
  const n = (k: string) => (typeof summary[k] === 'number' ? (summary[k] as number) : null);
  const items: [string, number | null][] =
    kind === 'pptx'
      ? [['Slides', n('slides')], ['Words', n('words')]]
      : [
          ['Pages', n('page_count')],
          ['Words', n('words')],
          ['Headings', n('headings')],
          ['Tables', n('tables')],
          ['Figures', n('figures')],
          ['References', n('references')],
        ];
  const sections = (summary.sections_found as string[] | undefined) ?? [];
  const warnings = (summary.warnings as string[] | undefined) ?? [];
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-3 gap-3 sm:grid-cols-6">
        {items.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-ink-700 bg-ink-900/60 px-3 py-2.5">
            <dt className="label">{label}</dt>
            <dd className="mt-1 font-serif text-xl font-semibold tabular-nums">{value ?? '—'}</dd>
          </div>
        ))}
      </dl>
      {sections.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="label mr-1">Sections found</span>
          {sections.map((r) => (
            <Badge key={r} tone="gold">{r.replace('_', ' ')}</Badge>
          ))}
        </div>
      )}
      {warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-paper-faint">
          {warnings.map((w) => (
            <li key={w}>ⓘ {w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PreviewPanel({
  version,
  kind,
  overlays,
  page,
  onPageChange,
}: {
  version: VersionOut;
  kind: string;
  overlays?: Overlay[];
  page?: number;
  onPageChange?: (p: number) => void;
}) {
  const ready = version.analysis_status === 'complete';
  const outline = useQuery({
    queryKey: ['versions', version.id, 'outline'],
    queryFn: () => api<OutlineNode[]>(`/versions/${version.id}/outline`),
    enabled: ready,
  });
  const pages = useQuery({
    queryKey: ['versions', version.id, 'pages'],
    queryFn: () => api<PageInfo[]>(`/versions/${version.id}/pages`),
    enabled: ready,
  });
  const [selected, setSelected] = useState<string | null>(null);

  if (!ready) return <AnalysisStatus version={version} />;
  return (
    <div className="grid gap-6 lg:grid-cols-[17rem_minmax(0,1fr)]">
      <aside className="surface h-fit max-h-[80vh] overflow-y-auto p-3 lg:sticky lg:top-6">
        <p className="label mb-2 px-2">{kind === 'pptx' ? 'Slides' : 'Structure'}</p>
        {outline.isPending ? (
          <div className="h-40 animate-pulse rounded bg-ink-800" />
        ) : (
          <StructureTree
            nodes={outline.data ?? []}
            selected={selected}
            onSelect={(nodeId) => {
              setSelected(nodeId);
              const m = /^s(\d+)$/.exec(nodeId);
              if (m) onPageChange?.(Number(m[1]));
            }}
          />
        )}
      </aside>
      <section aria-label="Page preview" className="min-w-0">
        {pages.data && pages.data.length > 0 ? (
          <PageViewer
            versionId={version.id}
            pages={pages.data}
            overlays={overlays}
            page={page}
            onPageChange={onPageChange}
            unit={kind === 'pptx' ? 'Slide' : 'Page'}
          />
        ) : pages.isPending ? (
          <div className="mx-auto aspect-[8.5/11] max-w-3xl animate-pulse rounded-md bg-ink-800" />
        ) : (
          <p className="text-sm text-paper-faint">Pages could not be rendered for this version.</p>
        )}
      </section>
    </div>
  );
}
