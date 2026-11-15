import { useId, type ReactNode } from 'react';

export interface TabDef {
  key: string;
  label: string;
  badge?: ReactNode;
}

/** Accessible tab list (arrow keys move between tabs). Panels are rendered by the parent. */
export function Tabs({ tabs, active, onChange }: { tabs: TabDef[]; active: string; onChange: (key: string) => void }) {
  const id = useId();
  return (
    <div
      role="tablist"
      className="flex gap-1 overflow-x-auto border-b border-ink-700"
      onKeyDown={(e) => {
        const i = tabs.findIndex((t) => t.key === active);
        if (e.key === 'ArrowRight') onChange(tabs[(i + 1) % tabs.length]!.key);
        if (e.key === 'ArrowLeft') onChange(tabs[(i - 1 + tabs.length) % tabs.length]!.key);
      }}
    >
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          id={`${id}-${t.key}`}
          aria-selected={active === t.key}
          tabIndex={active === t.key ? 0 : -1}
          onClick={() => onChange(t.key)}
          className={`-mb-px flex shrink-0 items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
            active === t.key ? 'border-accent text-paper' : 'border-transparent text-paper-faint hover:text-paper'
          }`}
        >
          {t.label}
          {t.badge}
        </button>
      ))}
    </div>
  );
}
