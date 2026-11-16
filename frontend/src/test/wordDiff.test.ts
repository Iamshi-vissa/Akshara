import { describe, expect, it } from 'vitest';

import { wordDiff } from '@/lib/wordDiff';

describe('wordDiff', () => {
  it('marks only the changed words', () => {
    const parts = wordDiff('This are a sentence with a error.', 'This is a sentence with an error.');
    expect(parts.filter((p) => p.kind === 'del').map((p) => p.text.trim())).toEqual(['are', 'a']);
    expect(parts.filter((p) => p.kind === 'add').map((p) => p.text.trim())).toEqual(['is', 'an']);
    expect(parts.map((p) => (p.kind === 'del' ? '' : p.text)).join('')).toBe('This is a sentence with an error.');
  });
  it('handles identical and empty inputs', () => {
    expect(wordDiff('same text', 'same text')).toEqual([{ kind: 'same', text: 'same text' }]);
    expect(wordDiff('', 'new')).toEqual([{ kind: 'add', text: 'new' }]);
  });
});
