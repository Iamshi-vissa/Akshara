import { useState } from 'react';

import { Icon } from '@/components/ui/Icon';
import { useAuthedBlob } from '@/lib/useAuthedBlob';

import type { Overlay, PageInfo } from './types';

const TONE: Record<Overlay['tone'], string> = {
  critical: 'border-sev-critical bg-sev-critical/15',
  high: 'border-sev-high bg-sev-high/15',
  medium: 'border-sev-medium bg-sev-medium/15',
  low: 'border-sev-low bg-sev-low/15',
  info: 'border-sev-info bg-sev-info/10',
};

function PageImage({ versionId, page, overlays, label }: { versionId: string; page: PageInfo; overlays: Overlay[]; label: string }) {
  const { url, error } = useAuthedBlob(`/versions/${versionId}/pages/${page.index}/image`);
  return (
    <div className="relative w-full overflow-hidden rounded-md bg-white shadow-[0_20px_60px_-20px_#000]" style={{ aspectRatio: `${page.width_pt} / ${page.height_pt}` }}>
      {url ? (
        <img src={url} alt={label} className="absolute inset-0 h-full w-full" draggable={false} />
      ) : (
        <div className={`absolute inset-0 grid place-items-center text-sm ${error ? 'text-sev-critical' : 'animate-pulse bg-ink-700'}`}>
          {error ? 'Preview unavailable' : ''}
        </div>
      )}
      {overlays.map((o) => (
        <div
          key={o.id}
          title={o.label}
          className={`pointer-events-auto absolute rounded-sm border-2 ${TONE[o.tone]}`}
          style={{
            left: `${(o.bbox[0] / page.width_pt) * 100}%`,
            top: `${(o.bbox[1] / page.height_pt) * 100}%`,
            width: `${((o.bbox[2] - o.bbox[0]) / page.width_pt) * 100}%`,
            height: `${((o.bbox[3] - o.bbox[1]) / page.height_pt) * 100}%`,
          }}
        />
      ))}
    </div>
  );
}

function Thumb({ versionId, page, active, onClick, unit }: { versionId: string; page: PageInfo; active: boolean; onClick: () => void; unit: string }) {
  const { url } = useAuthedBlob(`/versions/${versionId}/pages/${page.index}/image`);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active || undefined}
      aria-label={`${unit} ${page.index + 1}`}
      className={`relative w-full shrink-0 overflow-hidden rounded border-2 bg-white transition ${active ? 'border-accent' : 'border-transparent opacity-70 hover:opacity-100'}`}
      style={{ aspectRatio: `${page.width_pt} / ${page.height_pt}` }}
    >
      {url && <img src={url} alt="" className="absolute inset-0 h-full w-full" />}
      <span className="absolute right-1 bottom-1 rounded bg-ink-950/80 px-1 font-mono text-[10px] text-paper">{page.index + 1}</span>
    </button>
  );
}

export function PageViewer({
  versionId,
  pages,
  overlays = [],
  page: controlledPage,
  onPageChange,
  unit = 'Page',
}: {
  versionId: string;
  pages: PageInfo[];
  overlays?: Overlay[];
  page?: number;
  onPageChange?: (p: number) => void;
  unit?: 'Page' | 'Slide';
}) {
  const [localPage, setLocalPage] = useState(0);
  const current = controlledPage ?? localPage;
  const setPage = (p: number) => (onPageChange ? onPageChange(p) : setLocalPage(p));
  const page = pages[current];
  if (!page) return <p className="text-sm text-paper-faint">No rendered pages.</p>;

  return (
    <div className="grid gap-4 md:grid-cols-[6.5rem_minmax(0,1fr)]">
      <div className="hidden max-h-[75vh] space-y-2 overflow-y-auto pr-1 md:block">
        {pages.map((p) => (
          <Thumb key={p.index} versionId={versionId} page={p} active={p.index === current} onClick={() => setPage(p.index)} unit={unit} />
        ))}
      </div>
      <div className="min-w-0">
        <div className="mb-3 flex items-center justify-between text-sm text-paper-dim">
          <button type="button" className="rounded p-1 hover:bg-ink-800 disabled:opacity-30" onClick={() => setPage(current - 1)} disabled={current === 0} aria-label={`Previous ${unit.toLowerCase()}`}>
            <Icon name="back" />
          </button>
          <span className="font-mono text-xs">
            {unit} {current + 1} / {pages.length}
            {page.blank && <span className="ml-2 text-sev-medium">blank</span>}
          </span>
          <button type="button" className="rounded p-1 hover:bg-ink-800 disabled:opacity-30" onClick={() => setPage(current + 1)} disabled={current >= pages.length - 1} aria-label={`Next ${unit.toLowerCase()}`}>
            <Icon name="arrow" />
          </button>
        </div>
        <div className="mx-auto max-w-3xl">
          <PageImage versionId={versionId} page={page} overlays={overlays.filter((o) => o.page === current)} label={`${unit} ${current + 1}`} />
        </div>
      </div>
    </div>
  );
}
