import { Icon } from './Icon';

export type Sev = 'critical' | 'high' | 'medium' | 'low' | 'info';

export const SEV_ORDER: Sev[] = ['critical', 'high', 'medium', 'low', 'info'];

const STYLE: Record<Sev, string> = {
  critical: 'border-sev-critical/40 bg-sev-critical/10 text-sev-critical',
  high: 'border-sev-high/40 bg-sev-high/10 text-sev-high',
  medium: 'border-sev-medium/40 bg-sev-medium/10 text-sev-medium',
  low: 'border-sev-low/40 bg-sev-low/10 text-sev-low',
  info: 'border-sev-info/40 bg-sev-info/10 text-sev-info',
};

/** Severity is never shown by colour alone: icon + label + colour. */
export function SeverityBadge({ severity }: { severity: string }) {
  const s = (SEV_ORDER.includes(severity as Sev) ? severity : 'info') as Sev;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase ${STYLE[s]}`}>
      <Icon name={s === 'info' ? 'search' : 'alert'} className="size-3" />
      {s}
    </span>
  );
}

export function ScoreRing({ value, size = 88, label }: { value: number | null | undefined; size?: number; label?: string }) {
  const v = typeof value === 'number' ? value : null;
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  const color = v === null ? '#454c66' : v >= 85 ? '#4ade80' : v >= 70 ? '#fbbf24' : '#f87171';
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }} role="img" aria-label={`${label ?? 'Score'}: ${v ?? 'not available'}`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1f2435" strokeWidth={7} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={7} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={v === null ? c : c * (1 - v / 100)} className="transition-[stroke-dashoffset] duration-700" />
      </svg>
      <span className="absolute font-serif text-xl font-semibold tabular-nums">{v === null ? '—' : Math.round(v)}</span>
    </div>
  );
}
