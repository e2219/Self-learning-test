import { useCallback, useEffect, useRef, useState } from 'react';

function requestError(status: number, body: { detail?: unknown }, path: string) {
  if (status === 401 && path !== '/login') window.dispatchEvent(new Event('session-expired'));
  const detail = body.detail;
  return new Error(
    typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: { msg: string }) => d.msg).join('；')
        : '操作失败，请稍后重试。',
  );
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw requestError(response.status, body, path);
  }
  return body;
}

export function upload<T>(path: string, body: FormData, onProgress: (percent: number) => void) {
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', `/api${path}`);
    request.withCredentials = true;
    request.responseType = 'json';
    // No fixed timeout: a large textbook can take minutes to upload and parse.
    request.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.min(99, Math.round((event.loaded / event.total) * 100)));
    };
    request.upload.onload = () => onProgress(100);
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) resolve(request.response);
      else reject(requestError(request.status, request.response || {}, path));
    };
    request.onerror = () => reject(new Error('上传连接中断，请检查电脑服务和网络后重试。'));
    request.onabort = () => reject(new Error('上传已取消。'));
    request.send(body);
  });
}

export const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

export function useRemote<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const requestId = useRef(0);
  const reload = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const result = await api<T>(path);
      if (id === requestId.current) {
        setData(result);
        setError('');
      }
    } catch (err) {
      if (id === requestId.current) setError((err as Error).message);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    setData(null);
    setLoading(true);
    void reload();
    return () => {
      requestId.current++;
    };
  }, [reload]);
  return { data, error, loading, reload, setData };
}

export function date(value: string) {
  return new Date(value).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' });
}
