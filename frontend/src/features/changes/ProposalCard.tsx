import type { ProposalOut } from '@/api/client';
import { Badge } from '@/components/ui/Badge';
import { wordDiff } from '@/lib/wordDiff';

const RISK: Record<string, { label: string; tone: 'ok' | 'gold' | 'warn' }> = {
  formatting_only: { label: 'Formatting only', tone: 'ok' },
  structural: { label: 'Structure', tone: 'gold' },
  content_change: { label: 'Changes text', tone: 'warn' },
};
const ORIGIN: Record<string, string> = { deterministic: 'Rule-based', grammar: 'LanguageTool', llm: 'AI suggestion', user: 'Your edit' };

export function DiffView({ before, after }: { before: string; after: string }) {
  if (!before.includes(' ') && !after.includes(' ') && before.length < 60 && after.length < 60) {
    return (
      <p className="font-mono text-xs">
        <span className="rounded bg-sev-critical/15 px-1 text-sev-critical line-through">{before || '—'}</span>
        <span className="mx-2 text-paper-faint">→</span>
        <span className="rounded bg-ok/15 px-1 text-ok">{after || '—'}</span>
      </p>
    );
  }
  return (
    <p className="text-sm leading-relaxed whitespace-pre-wrap">
      {wordDiff(before, after).map((p, i) =>
        p.kind === 'same' ? (
          <span key={i} className="text-paper-dim">{p.text}</span>
        ) : p.kind === 'del' ? (
          <del key={i} className="mx-0.5 rounded bg-sev-critical/15 text-sev-critical decoration-sev-critical/60">{p.text}</del>
        ) : (
          <ins key={i} className="mx-0.5 rounded bg-ok/15 text-ok no-underline">{p.text}</ins>
        ),
      )}
    </p>
  );
}

export function ProposalCard({
  p,
  disabled,
  onDecide,
}: {
  p: ProposalOut;
  disabled: boolean;
  onDecide: (d: 'accepted' | 'rejected' | 'pending') => void;
}) {
  const risk = RISK[p.risk] ?? RISK.structural!;
  const state =
    p.decision === 'accepted' ? 'border-ok/40 bg-ok/5' : p.decision === 'rejected' ? 'border-ink-700 opacity-55' : 'border-ink-700 bg-ink-850/80';
  return (
    <li className={`rounded-xl border p-4 transition-colors ${state}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-paper">{p.title}</span>
        <Badge tone={risk.tone}>{risk.label}</Badge>
        <Badge>{ORIGIN[p.origin] ?? p.origin}</Badge>
        {p.rule_id && <span className="font-mono text-[10px] text-paper-faint">rule {p.rule_id}</span>}
      </div>
      <p className="mt-1 text-xs text-paper-faint">{p.rationale}</p>
      {(p.before || p.after) && (
        <div className="mt-3 rounded-lg border border-ink-700 bg-ink-950/60 p-3">
          <DiffView before={p.before} after={p.after} />
        </div>
      )}
      <div className="mt-3 flex gap-2" role="group" aria-label={`Decision for ${p.title}`}>
        <button type="button" disabled={disabled} aria-pressed={p.decision === 'accepted'}
          onClick={() => onDecide(p.decision === 'accepted' ? 'pending' : 'accepted')}
          className={`rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:opacity-40 ${p.decision === 'accepted' ? 'border-ok bg-ok/20 text-ok' : 'border-ink-600 text-paper-dim hover:border-ok/60 hover:text-ok'}`}>
          ✓ Accept
        </button>
        <button type="button" disabled={disabled} aria-pressed={p.decision === 'rejected'}
          onClick={() => onDecide(p.decision === 'rejected' ? 'pending' : 'rejected')}
          className={`rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:opacity-40 ${p.decision === 'rejected' ? 'border-sev-critical bg-sev-critical/15 text-sev-critical' : 'border-ink-600 text-paper-dim hover:border-sev-critical/60 hover:text-sev-critical'}`}>
          ✕ Reject
        </button>
      </div>
    </li>
  );
}
