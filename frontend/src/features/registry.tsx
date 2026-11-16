import { runJob } from '@/api/jobs';
import { FindingsPanel } from '@/features/inspection/FindingsPanel';
import { CompliancePanel } from '@/features/standards/CompliancePanel';
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
        rerun={{ label: 'Re-inspect', run: () => runJob(`/versions/${version.id}/inspections`) }}
        empty={<p className="text-sm text-paper-dim">This version has not been inspected yet.</p>}
      />
    ),
  },
  {
    key: 'compliance',
    label: 'Compliance',
    render: (doc, version) => <CompliancePanel doc={doc} version={version} />,
  },
];
