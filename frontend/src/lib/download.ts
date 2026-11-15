import { apiFetch } from '@/api/client';

/** Fetch an authenticated file and hand it to the browser as a download. */
export async function downloadFrom(path: string, filename: string): Promise<void> {
  const res = await apiFetch(path);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
