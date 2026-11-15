import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';

import { api, type QualityRow } from '@/api/client';
import BlurText from '@/components/reactbits/BlurText';
import { KindBadge } from '@/components/ui/Badge';
import { ScoreRing } from '@/components/ui/Severity';
import { DimensionBars } from '@/features/inspection/FindingsPanel';
import { relativeTime } from '@/lib/format';

export function QualityPage() {
  const q = useQuery({ queryKey: ['quality'], queryFn: () => api<QualityRow[]>('/quality') });
  const rows = q.data ?? [];
  const avg = rows.length ? rows.reduce((s, r) => s + ((r.scores.overall as number) ?? 0), 0) / rows.length : null;
  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="label text-gold/80">Quality dashboard</p>
          <BlurText text="How your documents measure up." className="mt-2 font-serif text-4xl font-semibold" animateBy="words" delay={60} trigger="load" />
          <p className="mt-2 max-w-2xl text-paper-dim">Latest inspection of the current version of each document. Scores come only from checks that actually ran.</p>
        </div>
        <div className="flex items-center gap-4">
          <ScoreRing value={avg} size={104} label="Average quality" />
          <div className="text-sm text-paper-dim">Average across<br /><span className="font-serif text-2xl text-paper">{rows.length}</span> documents</div>
        </div>
      </header>
      {q.isPending ? (
        <div className="surface h-64 animate-pulse" />
      ) : rows.length === 0 ? (
        <div className="surface p-10 text-center">
          <p className="font-serif text-lg">No inspected documents yet</p>
          <p className="mt-1 text-sm text-paper-faint">Upload a document: it is inspected automatically.</p>
        </div>
      ) : (
        <ul className="space-y-3">
          {rows.map((r) => (
            <li key={r.document_id}>
              <Link to={`/documents/${r.document_id}?tab=inspection`} className="surface flex flex-wrap items-center gap-6 p-5 transition-colors hover:border-ink-500">
                <ScoreRing value={r.scores.overall as number} size={64} label={`${r.title} quality`} />
                <div className="min-w-48 flex-1">
                  <div className="flex items-center gap-2"><KindBadge kind={r.kind as 'docx'} /><span className="font-medium">{r.title}</span></div>
                  <p className="mt-1 text-xs text-paper-faint">{r.total} findings · checked {relativeTime(r.created_at)}</p>
                </div>
                <div className="w-full md:w-[28rem]"><DimensionBars dims={(r.scores.dimensions ?? {}) as Record<string, number>} /></div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
