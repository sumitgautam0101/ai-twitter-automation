// HTTP client for the OpenX service API (proxied via /api in dev).
import { useCallback, useEffect, useRef, useState } from 'react';

async function req(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch { /* not json */ }
    throw new Error(`${method} ${path} → ${res.status}: ${detail}`);
  }
  return res.json();
}

export const api = {
  get: (path) => req(path),
  post: (path, body) => req(path, { method: 'POST', body: body || {} }),
  patch: (path, body) => req(path, { method: 'PATCH', body }),
  put: (path, body) => req(path, { method: 'PUT', body }),
  del: (path, body) => req(path, { method: 'DELETE', body }),
};

// Poll a GET endpoint. Returns { data, error, reload }. `interval` in ms
// (0 = fetch once). Re-fetches when `path` changes.
export function usePoll(path, interval = 0) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const alive = useRef(true);

  const reload = useCallback(() => {
    if (!path) return;
    api
      .get(path)
      .then((d) => {
        if (alive.current) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => alive.current && setError(e));
  }, [path]);

  useEffect(() => {
    alive.current = true;
    reload();
    if (!interval) return () => { alive.current = false; };
    const t = setInterval(reload, interval);
    return () => {
      alive.current = false;
      clearInterval(t);
    };
  }, [reload, interval]);

  return { data, error, reload };
}
