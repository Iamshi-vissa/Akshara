import type { OutlineNode } from './types';

const ROLE_LABEL: Record<string, string> = {
  abstract: 'Abstract',
  introduction: 'Intro',
  methodology: 'Method',
  results: 'Results',
  conclusion: 'Conclusion',
  references: 'Refs',
  appendix: 'Appendix',
  related_work: 'Related',
  discussion: 'Discussion',
  keywords: 'Keywords',
};

function Node({ node, depth, onSelect, selected }: { node: OutlineNode; depth: number; onSelect?: (id: string) => void; selected?: string | null }) {
  const role = ROLE_LABEL[node.role];
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect?.(node.id)}
        className={`flex w-full items-baseline gap-2 rounded-md py-1.5 pr-2 text-left text-sm transition-colors hover:bg-ink-800 ${
          selected === node.id ? 'bg-accent-soft text-paper' : 'text-paper-dim'
        }`}
        style={{ paddingLeft: `${0.5 + depth * 0.9}rem` }}
      >
        <span className={`min-w-0 flex-1 truncate ${node.level <= 1 ? 'font-medium text-paper' : ''}`}>{node.text || 'Untitled'}</span>
        {role && <span className="shrink-0 rounded border border-gold/25 px-1 font-mono text-[10px] text-gold/80">{role}</span>}
      </button>
      {node.children.length > 0 && (
        <ul>
          {node.children.map((c) => (
            <Node key={c.id} node={c} depth={depth + 1} onSelect={onSelect} selected={selected} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function StructureTree({ nodes, onSelect, selected }: { nodes: OutlineNode[]; onSelect?: (id: string) => void; selected?: string | null }) {
  if (nodes.length === 0) {
    return <p className="px-2 py-3 text-sm text-paper-faint">No headings were detected in this document.</p>;
  }
  return (
    <ul aria-label="Document structure" className="space-y-0.5">
      {nodes.map((n) => (
        <Node key={n.id} node={n} depth={0} onSelect={onSelect} selected={selected} />
      ))}
    </ul>
  );
}
