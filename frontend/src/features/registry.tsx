import { api } from '@/api/client';
import { FindingsPanel } from '@/features/inspection/FindingsPanel';
import type { WorkspaceTab } from '@/pages/DocumentPage';

/** Workspace tabs contributed by each module, in display order. */
export const workspaceTabs: WorkspaceTab[] = [
  {
    key: 'inspection',
    label: 'Inspection',
    render: (_doc, version) => (
      <FindingsPanel
        version={version}
        kind="inspection"
        rerun={{ label: 'Re-inspect', run: () => api(`/versions/${version.id}/inspections`, { method: 'POST' }) }}
        empty={<p className="text-sm text-paper-dim">This version has not been inspected yet.</p>}
      />
    ),
  },
];
