import { runJob } from '@/api/jobs';
import { FindingsPanel } from '@/features/inspection/FindingsPanel';
import { ChangesPanel } from '@/features/changes/ChangesPanel';
import { EditPanel } from '@/features/changes/EditPanel';
import { CompliancePanel } from '@/features/standards/CompliancePanel';
import { ReferencesPanel } from '@/features/references/ReferencesPanel';
import { VisualPanel } from '@/features/visual/VisualPanel';
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
    key: 'visual',
    label: 'Visual',
    render: (doc, version) => <VisualPanel version={version} unit={doc.kind === 'pptx' ? 'Slide' : 'Page'} />,
  },
  {
    key: 'references',
    label: 'References',
    render: (doc, version) => <ReferencesPanel doc={doc} version={version} />,
  },
  {
    key: 'compliance',
    label: 'Compliance',
    render: (doc, version) => <CompliancePanel doc={doc} version={version} />,
  },
  {
    key: 'changes',
    label: 'Changes',
    render: (doc, version) => <ChangesPanel doc={doc} version={version} />,
  },
  {
    key: 'edit',
    label: 'Edit',
    render: (doc, version) => <EditPanel doc={doc} version={version} />,
  },
];
