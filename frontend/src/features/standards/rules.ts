/** Loose view of a UDSE rule as returned by the API (the server validates the full schema). */
export interface UdseRule {
  id: string;
  title: string;
  category: string;
  kind: 'hard' | 'soft';
  severity: string;
  applies_to?: string[];
  selector: { node: string; where?: Record<string, unknown> };
  check: { op: string; property?: string; value?: unknown; values?: unknown[]; min?: number; max?: number; unit?: string; tolerance?: number; pattern?: string };
  message?: string;
  fix?: { strategy?: string; auto?: boolean; hint?: string };
  provenance?: { source: string; locator?: string; url?: string; quote?: string; verification: string; notes?: string };
  enabled?: boolean;
}

const UNIT = (u?: string) => (u && u !== 'none' ? ` ${u}` : '');

/** Human summary of what a rule checks, e.g. "margins.left = 1 in (± 0.05)". */
export function describeCheck(r: UdseRule): string {
  const c = r.check;
  const target = `${r.selector.node}${r.selector.where && Object.keys(r.selector.where).length ? ` (${Object.entries(r.selector.where).map(([k, v]) => `${k}=${String(v)}`).join(', ')})` : ''}`;
  const prop = c.property ?? '';
  switch (c.op) {
    case 'equals':
      return `${prop} = ${String(c.value)}${UNIT(c.unit)}${c.tolerance ? ` (± ${c.tolerance})` : ''}`;
    case 'in_set':
      return `${prop} ∈ {${(c.values ?? []).join(', ')}}`;
    case 'in_range':
      return `${prop} between ${c.min ?? '…'} and ${c.max ?? '…'}${UNIT(c.unit)}`;
    case 'matches':
      return `${prop} matches /${c.pattern}/`;
    case 'present':
      return `${target} must exist`;
    case 'absent':
      return `${target} must not exist`;
    case 'max_words':
      return `${target}: at most ${c.max} words`;
    case 'min_words':
      return `${target}: at least ${c.min} words`;
    case 'sequence':
      return `${target}: numbered 1, 2, 3…${c.pattern ? ` as /${c.pattern}/` : ''}`;
    case 'citation_style':
      return `citations are ${String(c.value)}`;
    case 'reference_order':
      return `references in ${String(c.value)} order`;
    default:
      return `${c.op}${prop ? ` · ${prop}` : ''}`;
  }
}

export const VERIFICATION_LABEL: Record<string, { label: string; tone: 'ok' | 'warn' | 'neutral' | 'gold' }> = {
  primary: { label: 'Verified (official source)', tone: 'ok' },
  secondary: { label: 'Checked against secondary sources', tone: 'gold' },
  unverified: { label: 'Unverified', tone: 'warn' },
  extracted: { label: 'Extracted from guideline', tone: 'neutral' },
  user: { label: 'Your rule', tone: 'neutral' },
};
