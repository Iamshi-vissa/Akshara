import type { FindingOut } from '@/api/client';
import { SeverityBadge } from '@/components/ui/Severity';

export function FindingCard({
  finding,
  active,
  onSelect,
  onToggleDismiss,
}: {
  finding: FindingOut;
  active: boolean;
  onSelect: () => void;
  onToggleDismiss: () => void;
}) {
  const dismissed = finding.status === 'dismissed';
  return (
    <li>
      <article
        className={`rounded-xl border p-4 transition-colors ${active ? 'border-accent bg-accent-soft' : 'border-ink-700 bg-ink-850/80 hover:border-ink-600'} ${dismissed ? 'opacity-55' : ''}`}
      >
        <button type="button" onClick={onSelect} className="block w-full text-left" aria-pressed={active}>
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={finding.severity} />
            {finding.constraint_kind && (
              <span className="rounded border border-ink-600 px-1.5 font-mono text-[10px] text-paper-faint uppercase">{finding.constraint_kind}</span>
            )}
            <span className="font-mono text-[10px] text-paper-faint">{finding.code}</span>
            {finding.confidence < 1 && (
              <span className="text-[10px] text-paper-faint" title="Based on structure inferred from the PDF layout">
                inferred · {Math.round(finding.confidence * 100)}%
              </span>
            )}
          </div>
          <p className="mt-2 text-sm font-medium text-paper">{finding.message}</p>
          {finding.location && <p className="mt-0.5 text-xs text-gold/80">{finding.location}</p>}
        </button>
        {active && (
          <div className="mt-3 space-y-2 border-t border-ink-700 pt-3 text-sm">
            <p className="text-paper-dim">{finding.explanation}</p>
            <p className="text-ok/90">
              <span className="font-semibold">Recommended: </span>
              {finding.recommendation}
            </p>
            {finding.rule_id && <p className="font-mono text-xs text-paper-faint">Rule {finding.rule_id}</p>}
            <button type="button" onClick={onToggleDismiss} className="text-xs font-medium text-paper-faint underline-offset-4 hover:text-paper hover:underline">
              {dismissed ? 'Re-open finding' : 'Dismiss (this is intended)'}
            </button>
          </div>
        )}
      </article>
    </li>
  );
}
