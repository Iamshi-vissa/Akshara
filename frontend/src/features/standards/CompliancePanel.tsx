import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, json, type DocumentOut, type StandardOut, type VersionOut } from '@/api/client';
import { runJob } from '@/api/jobs';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ScoreRing, SeverityBadge } from '@/components/ui/Severity';
import { FindingsPanel, useLatestRun } from '@/features/inspection/FindingsPanel';

interface RuleResult {
  id: string;
  title: string;
  kind: string;
  severity: string;
  status: 'pass' | 'fail' | 'not_evaluated';
  reason: string;
  verification: string | null;
}

const STATUS: Record<RuleResult['status'], { label: string; cls: string }> = {
  pass: { label: 'Pass', cls: 'text-ok' },
  fail: { label: 'Fail', cls: 'text-sev-critical' },
  not_evaluated: { label: 'Not evaluated', cls: 'text-paper-faint' },
};

export function CompliancePanel({ doc, version }: { doc: DocumentOut; version: VersionOut }) {
  const qc = useQueryClient();
  const standards = useQuery({ queryKey: ['standards'], queryFn: () => api<StandardOut[]>('/standards') });
  const latest = useLatestRun(version.id, 'udse', version.analysis_status === 'complete');
  const options = (standards.data ?? []).flatMap((s) =>
    s.versions.filter((v) => s.builtin || v.status === 'published').map((v) => ({ id: v.id, label: `${s.name}${s.builtin ? '' : ` (v${v.version})`}` })),
  );
  const [selected, setSelected] = useState<string>('');
  const current = selected || latest.data?.standard_version_id || doc.applied_standard_version_id || options[0]?.id || '';
  const validate = useMutation({
    mutationFn: (svid: string) => runJob(`/versions/${version.id}/validations`, json({ standard_version_id: svid })),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['versions', version.id, 'runs', 'udse'] });
      void qc.invalidateQueries({ queryKey: ['documents', doc.id] });
    },
  });

  const picker = (
    <div className="surface flex flex-wrap items-end gap-3 p-4">
      <label className="block min-w-64 flex-1">
        <span className="mb-1 block text-xs text-paper-faint">Standard</span>
        <select value={current} onChange={(e) => setSelected(e.target.value)} className="h-10 w-full rounded-lg border border-ink-600 bg-ink-900 px-3 text-sm">
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </label>
      <Button loading={validate.isPending} disabled={!current} onClick={() => validate.mutate(current)}>Validate against standard</Button>
      {validate.isError && <p role="alert" className="w-full text-sm text-sev-critical">{(validate.error as Error).message}</p>}
    </div>
  );

  return (
    <div className="space-y-6">
      {picker}
      <FindingsPanel
        version={version}
        kind="udse"
        empty={<p className="text-sm text-paper-dim">Choose a standard and validate this version against it.</p>}
        header={(run) => {
          const c = run.stats.compliance as Record<string, number | string | boolean | null>;
          const std = run.stats.standard as { name: string; version: string; notice?: string };
          const rules = (run.stats.rules ?? []) as RuleResult[];
          const verdict = String(c.verdict);
          return (
            <div className="w-full space-y-5">
              <div className="flex flex-wrap items-center gap-6">
                <ScoreRing value={c.score as number | null} label="Compliance" />
                <div className="min-w-56 flex-1">
                  <p className="label">Compliance with</p>
                  <p className="font-serif text-xl">{std.name} <span className="text-sm text-paper-faint">v{std.version}</span></p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge tone={verdict === 'compliant' ? 'ok' : verdict === 'not compliant' ? 'warn' : 'neutral'}>{verdict}</Badge>
                    <Badge>hard {String(c.hard_pass)}✓ {String(c.hard_fail)}✗</Badge>
                    <Badge>soft {String(c.soft_pass)}✓ {String(c.soft_fail)}✗</Badge>
                    {Number(c.not_evaluated) > 0 && <Badge>{String(c.not_evaluated)} not evaluated</Badge>}
                  </div>
                  {c.cap_applied && (
                    <p className="mt-2 text-xs text-paper-faint">Raw score {String(c.raw_score)} capped at 69 because a hard rule failed.</p>
                  )}
                </div>
              </div>
              {std.notice && <p className="rounded-lg border border-gold/25 bg-gold-soft px-3 py-2 text-xs text-gold">{std.notice}</p>}
              <details>
                <summary className="cursor-pointer text-sm text-paper-dim">Rule checklist ({rules.length})</summary>
                <ul className="mt-3 divide-y divide-ink-700/60 rounded-lg border border-ink-700">
                  {rules.map((r) => (
                    <li key={r.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                      <span className={`w-28 shrink-0 text-xs font-semibold ${STATUS[r.status].cls}`}>{STATUS[r.status].label}</span>
                      <span className="min-w-0 flex-1">{r.title}{r.reason && <span className="ml-2 text-xs text-paper-faint">— {r.reason}</span>}</span>
                      <span className="font-mono text-[10px] text-paper-faint uppercase">{r.kind}</span>
                      <SeverityBadge severity={r.severity} />
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          );
        }}
      />
    </div>
  );
}
