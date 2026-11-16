export type DiffPart = { kind: 'same' | 'add' | 'del'; text: string };

/** Word-level diff (LCS). Inputs are short paragraphs, so O(n·m) is fine; long inputs fall back to whole-block replace. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.split(/(\s+)/).filter(Boolean);
  const b = after.split(/(\s+)/).filter(Boolean);
  if (a.length * b.length > 400_000) return [{ kind: 'del', text: before }, { kind: 'add', text: after }];
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--) dp[i]![j] = a[i] === b[j] ? dp[i + 1]![j + 1]! + 1 : Math.max(dp[i + 1]![j]!, dp[i]![j + 1]!);
  const out: DiffPart[] = [];
  const push = (kind: DiffPart['kind'], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push('same', a[i++]!);
      j++;
    } else if (dp[i + 1]![j]! >= dp[i]![j + 1]!) push('del', a[i++]!);
    else push('add', b[j++]!);
  }
  while (i < a.length) push('del', a[i++]!);
  while (j < b.length) push('add', b[j++]!);
  return out;
}
