import { api, ApiError, type JobOut } from './client';

const DONE = new Set(['succeeded', 'failed', 'cancelled']);

/**
 * Start a background job (a POST that returns a JobOut) and wait until it finishes.
 * Works in both executor modes: inline jobs come back already finished; Celery jobs are polled.
 */
export async function runJob(path: string, init: RequestInit = {}, timeoutMs = 180_000): Promise<JobOut> {
  let job = await api<JobOut>(path, { method: 'POST', ...init });
  const deadline = Date.now() + timeoutMs;
  let delay = 400;
  while (!DONE.has(job.status)) {
    if (Date.now() > deadline) throw new ApiError(0, 'JOB_TIMEOUT', 'This is taking longer than expected. Check back shortly.');
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay * 1.5, 2000);
    job = await api<JobOut>(`/jobs/${job.id}`);
  }
  if (job.status !== 'succeeded') {
    throw new ApiError(0, job.error_code ?? 'JOB_FAILED', job.error_message ?? 'The job failed.');
  }
  return job;
}
