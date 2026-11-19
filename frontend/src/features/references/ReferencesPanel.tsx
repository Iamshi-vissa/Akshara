import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';

import { api, ApiError, json, type ChangeSetOut, type DocumentOut, type VersionOut } from '@/api/client';
import { runJob } from '@/api/jobs';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useLatestRun } from '@/features/inspection/FindingsPanel';
import { formatDate } from '@/lib/format';

interface Person { family: string; given: string }
interface RecordData { title: string; authors: Person[]; year: number | null; container: string; doi: string; source: string }
interface UrlCheck { url: string; ok: boolean; checked: boolean; status: number | null; reason: string }
interface Item {
  node_id: string;
  text: string;
  status: 'verified' | 'mismatch' | 'not_found' | 'possible_match' | 'unverified' | 'error';
  parsed: { label: string; doi: string; title: string };
  record: RecordData | null;
  differences: string[];
  suggestion?: string;
  urls: UrlCheck[];
  error?: string;
}

const STATUS: Record<Item['status'], { label: string; tone: 'ok' | 'warn' | 'neutral' | 'gold' | 'accent' }> = {
  verified: { label: 'Verified', tone: 'ok' },
  mismatch: { label: 'Does not match its DOI', tone: 'warn' },
  not_found: { label: 'DOI not registered', tone: 'warn' },
  possible_match: { label: 'Possible match — confirm', tone: 'gold' },
  unverified: { label: 'Not verifiable', tone: 'neutral' },
  error: { label: 'Lookup failed', tone: 'neutral' },
};

const strip = (s: string) => s.replace(/\*/g, '');

export function ReferencesPanel({ doc, version }: { doc: DocumentOut; version: VersionOut }) {
  const qc = useQueryClient();
  const ready = version.analysis_status === 'complete';
  const run = useLatestRun(version.id, 'references', ready);
  const [style, setStyle] = useState<string>('');
  const [proposed, setProposed] = useState<Record<string, boolean>>({});

  const verify = useMutation({
    mutationFn: () => runJob(`/versions/${version.id}/references/verify`, json(style ? { style } : {}), 300_000),
    onSettled: () => void qc.invalidateQueries({ queryKey: ['versions', version.id, 'runs', 'references'] }),
  });
  const propose = useMutation({
    mutationFn: (it: Item) =>
      api<ChangeSetOut>(`/documents/${doc.id}/changesets`, {
        method: 'POST',
        ...json({ source: 'manual', edits: [{ node_id: it.node_id, after: strip(it.suggestion ?? '') }] }),
      }),
    onSuccess: (_cs, it) => {
      setProposed((p) => ({ ...p, [it.node_id]: true }));
      void qc.invalidateQueries({ queryKey: ['documents', doc.id] });
    },
  });

  if (!ready) return <p className="text-sm text-paper-faint">Available once analysis completes.</p>;
  const stats = run.data?.stats as { items?: Item[]; style?: string; counts?: Record<string, number> } | undefined;
  const items = stats?.items ?? [];

  return (
    <div className="space-y-6">
      <section className="surface flex flex-wrap items-end justify-between gap-4 p-5" aria-label="Check references">
        <div className="max-w-2xl">
          <h2 className="font-serif text-xl font-semibold">Reference check</h2>
          <p className="mt-1 text-sm text-paper-dim">
            Each entry's DOI is looked up in Crossref and OpenAlex and compared with what you wrote; entries without a DOI are
            searched by title, and cited links are tested. Only the reference text is sent, never the rest of the document.
            AKSHARA never fills in details on its own — corrections come from the registry record and you approve each one.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <label className="text-sm">
            <span className="mb-1 block text-paper-dim">Style</span>
            <select value={style} onChange={(e) => setStyle(e.target.value)} className="h-10 rounded-lg border border-ink-600 bg-ink-900 px-3">
              <option value="">Automatic</option>
              <option value="apa">APA 7</option>
              <option value="ieee">IEEE</option>
              <option value="mla">MLA 9</option>
            </select>
          </label>
          <Button onClick={() => verify.mutate()} loading={verify.isPending}>{run.data ? 'Check again' : 'Check references'}</Button>
        </div>
      </section>
      {verify.isError && <p role="alert" className="text-sm text-sev-critical">{(verify.error as ApiError).message}</p>}
      {propose.isError && <p role="alert" className="text-sm text-sev-critical">{(propose.error as ApiError).message}</p>}

      {run.isPending ? (
        <div className="surface h-40 animate-pulse" />
      ) : !run.data ? (
        <p className="text-sm text-paper-faint">Not checked yet.</p>
      ) : (
        <>
          <p className="text-xs text-paper-faint">
            Checked {formatDate(run.data.created_at)} · {items.length} references · style {stats?.style?.toUpperCase()} ·{' '}
            {Object.entries(stats?.counts ?? {}).map(([k, n]) => `${n} × ${STATUS[k as Item["status"]]?.label ?? k}`).join(', ')}
          </p>
          <ol className="space-y-3" aria-label="References">
            {items.map((it) => {
              const st = STATUS[it.status];
              return (
                <li key={it.node_id} className="surface space-y-3 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={st.tone}>{st.label}</Badge>
                    {it.record?.doi && (
                      <a className="font-mono text-xs text-accent hover:underline" href={`https://doi.org/${it.record.doi}`} target="_blank" rel="noreferrer noopener">
                        doi:{it.record.doi}
                      </a>
                    )}
                    {it.record && <span className="text-xs text-paper-faint">via {it.record.source === 'openalex' ? 'OpenAlex' : 'Crossref'}</span>}
                  </div>
                  <p className="text-sm leading-relaxed">{it.text}</p>
                  {it.differences.length > 0 && (
                    <ul className="list-disc pl-5 text-xs text-sev-medium">{it.differences.map((d) => <li key={d}>{d}</li>)}</ul>
                  )}
                  {it.error && <p className="text-xs text-paper-faint">{it.error} Nothing was concluded about this entry.</p>}
                  {it.urls.map((u) => (
                    <p key={u.url} className={`text-xs ${u.checked && !u.ok ? 'text-sev-medium' : 'text-paper-faint'}`}>
                      Link {u.url}: {u.ok ? `works${u.status ? ` (HTTP ${u.status})` : ''}` : u.checked ? `broken — ${u.reason}` : `not checked — ${u.reason}`}
                    </p>
                  ))}
                  {it.suggestion && it.status !== 'verified' && (
                    <div className="rounded-lg border border-ink-600 bg-ink-900/60 p-3">
                      <p className="label">{it.status === 'possible_match' ? 'If this is the work you cited' : 'From the registered record'}</p>
                      <p className="mt-1 text-sm">{strip(it.suggestion)}</p>
                      <div className="mt-2 flex items-center gap-3">
                        {proposed[it.node_id] ? (
                          <Link to="?tab=changes" className="text-sm text-accent">Proposed — review it in Changes</Link>
                        ) : (
                          <Button size="sm" variant="secondary" loading={propose.isPending && propose.variables?.node_id === it.node_id} onClick={() => propose.mutate(it)}>
                            Propose this correction
                          </Button>
                        )}
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </>
      )}
    </div>
  );
}
