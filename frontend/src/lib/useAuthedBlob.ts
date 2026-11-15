import { useEffect, useState } from 'react';

import { apiFetch } from '@/api/client';

/** Load an authenticated binary (e.g. a page image) and expose it as an object URL. */
export function useAuthedBlob(path: string | null): { url: string | null; error: boolean } {
  const [state, setState] = useState<{ url: string | null; error: boolean; path: string | null }>({
    url: null,
    error: false,
    path: null,
  });
  useEffect(() => {
    if (!path) return;
    let revoked = false;
    let objectUrl: string | null = null;
    apiFetch(path)
      .then((res) => res.blob())
      .then((blob) => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, error: false, path });
      })
      .catch(() => !revoked && setState({ url: null, error: true, path }));
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);
  return state.path === path ? { url: state.url, error: state.error } : { url: null, error: false };
}
