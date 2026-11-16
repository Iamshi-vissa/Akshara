import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, downloadVersion, json, type DocumentOut, type VersionOut } from '@/api/client';
import { runJob } from '@/api/jobs';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { formatBytes, formatDate } from '@/lib/format';

import { DiffView } from './ProposalCard';

interface DiffResult {
  counts: Record<string, number>;
  changes: { type: string; node_type: string; text?: string; before?: string; after?: string; changed?: Record<string, [unknown, unknown]> }[];
  page_setup: Record<string, unknown>[];
}

const LABEL: Record<string, string> = { upload: 'Original upload', changeset: 'Approved changes', revert: 'Restored', generation: 'Generated' };

export function VersionHistory({ doc, versions }: { doc: DocumentOut; versions: VersionOut[] }) {
  const qc = useQueryClient();
  const current = doc.current_version;
  const [compare, setCompare] = useState<string | null>(null);
  const diff = useQuery({
    queryKey: ['diff', compare, current?.id],
    queryFn: () => api<DiffResult>(`/documents/${doc.id}/diff?from_version=${compare}&to_version=${current!.id}`),
    enabled: !!compare && !!current,
  });
  const restore = useMutation({
    mutationFn: (versionId: string) => runJob(`/documents/${doc.id}/revert`, json({ version_id: versionId })),
    onSettled: () => void qc.invalidateQueries({ queryKey: ['documents', doc.id] }),
  });

  return (
    <section aria-labelledby="versions-h" className="space-y-4">
      <h2 id="versions-h" className="flex items-center gap-2 font-serif text-2xl font-semibold">
        <Icon name="history" className="size-5 text-gold" /> Version history
      </h2>
      {restore.isError && <p role="alert" className="text-sm text-sev-critical">{(restore.error as Error).message}</p>}
      <ol className="surface divide-y divide-ink-700/70">
        {versions.map((ver) => {
          const isCurrent = ver.id === current?.id;
          return (
            <li key={ver.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
              <span className="grid size-9 place-items-center rounded-full border border-gold/30 bg-gold-soft font-mono text-sm text-gold">{ver.number}</span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {LABEL[ver.created_by] ?? ver.created_by}
                  {isCurrent && <Badge tone="accent">current</Badge>}
                </p>
                <p className="text-xs text-paper-faint">
                  {formatDate(ver.created_at)} · {formatBytes(ver.size_bytes)} · <span className="font-mono">{ver.sha256.slice(0, 12)}…</span>
                </p>
              </div>
              {!isCurrent && ver.analysis_status === 'complete' && current?.analysis_status === 'complete' && (
                <Button size="sm" variant="ghost" onClick={() => setCompare(compare === ver.id ? null : ver.id)}>
                  {compare === ver.id ? 'Hide changes' : 'Compare with current'}
                </Button>
              )}
              {!isCurrent && (
                <Button size="sm" variant="secondary" loading={restore.isPending && restore.variables === ver.id} onClick={() => restore.mutate(ver.id)}>
                  Restore
                </Button>
              )}
              <Button variant="secondary" size="sm" onClick={() => void downloadVersion(ver.id, doc.original_filename)}>
                <Icon name="download" /> Download
              </Button>
              {compare === ver.id && (
                <div className="w-full rounded-lg border border-ink-700 bg-ink-950/50 p-4">
                  {diff.isPending ? (
                    <div className="h-20 animate-pulse rounded bg-ink-800" />
                  ) : diff.data ? (
                    <div className="space-y-3 text-sm">
                      <p className="text-paper-dim">
                        {diff.data.counts.text} text · {diff.data.counts.format} formatting · {diff.data.counts.added} added ·{' '}
                        {diff.data.counts.removed} removed{diff.data.page_setup.length ? ' · page setup changed' : ''}
                      </p>
                      <ul className="max-h-96 space-y-2 overflow-y-auto">
                        {diff.data.changes.map((c, i) => (
                          <li key={i} className="rounded border border-ink-700 p-2">
                            <span className="label mr-2">{c.type}</span>
                            {c.type === 'text' && <DiffView before={c.before ?? ''} after={c.after ?? ''} />}
                            {c.type === 'format' && (
                              <span className="text-paper-dim">
                                “{c.text}” — {Object.entries(c.changed ?? {}).map(([k, [a, b]]) => `${k}: ${String(a)} → ${String(b)}`).join(', ')}
                              </span>
                            )}
                            {(c.type === 'added' || c.type === 'removed') && <span className="text-paper-dim">{c.node_type}: “{c.text}”</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p className="text-sm text-sev-critical">Could not compare these versions.</p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
