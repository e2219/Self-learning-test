import { useCallback, useEffect, useRef, useState } from 'react';

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') window.dispatchEvent(new Event('session-expired'));
    const detail = body.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d: {msg: string}) => d.msg).join('；') : '操作失败，请稍后重试。');
  }
  return body;
}

export const json = (method: string, body?: unknown): RequestInit => ({ method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export function useRemote<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const requestId = useRef(0);
  const reload = useCallback(async () => {
    const id = ++requestId.current;
    try { const result = await api<T>(path); if (id === requestId.current) { setData(result); setError(''); } }
    catch (err) { if (id === requestId.current) setError((err as Error).message); }
    finally { if (id === requestId.current) setLoading(false); }
  }, [path]);
  useEffect(() => { setData(null); setLoading(true); void reload(); return () => { requestId.current++; }; }, [reload]);
  return { data, error, loading, reload, setData };
}

export function date(value: string) { return new Date(value).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' }); }
