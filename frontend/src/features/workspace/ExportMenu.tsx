import { useMutation } from '@tanstack/react-query';

import { json, type DocumentOut, type VersionOut } from '@/api/client';
import { runJob } from '@/api/jobs';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { downloadFrom } from '@/lib/download';

const FORMATS: Record<string, ('docx' | 'pdf' | 'pptx')[]> = { docx: ['docx', 'pdf'], pptx: ['pptx', 'pdf'], pdf: ['pdf'] };

/** Export the current version. Conversions run in the sandboxed renderer; the original is untouched. */
export function ExportMenu({ doc, version }: { doc: DocumentOut; version: VersionOut }) {
  const exp = useMutation({
    mutationFn: async (format: string) => {
      const job = await runJob(`/versions/${version.id}/exports`, json({ format }));
      const r = job.result as { export_id: string; filename: string };
      await downloadFrom(`/exports/${r.export_id}/file`, r.filename);
    },
  });
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Export">
      {FORMATS[doc.kind]!.map((f) => (
        <Button key={f} size="sm" variant="secondary" loading={exp.isPending && exp.variables === f} onClick={() => exp.mutate(f)}>
          <Icon name="download" /> {f.toUpperCase()}
        </Button>
      ))}
      {exp.isError && <span role="alert" className="text-xs text-sev-critical">{(exp.error as Error).message}</span>}
    </div>
  );
}
