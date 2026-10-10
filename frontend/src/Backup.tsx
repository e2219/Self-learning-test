import { useRef, useState } from 'react';
import { Download } from 'lucide-react';
import { api, json } from './api';
import { Notice } from './ui';

export function Backup() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [done, setDone] = useState(false);
  const pending = useRef(false);
  async function download() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    setDone(false);
    try {
      const result = await api<{ url: string; filename: string }>('/backups', json('POST'));
      const link = document.createElement('a');
      link.href = result.url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setDone(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="panel form-section">
      <h2>数据备份</h2>
      <p>
        下载课程、教材、试卷和作答记录，方便换电脑或更新前留存。不包含 API
        Key、应用设置、登录会话和访问口令。
      </p>
      <button className="button secondary" disabled={busy} onClick={() => void download()}>
        <Download size={16} />
        {busy ? '正在打包…' : '一键备份'}
      </button>
      <p className="field-help">
        教材较大时需要一些时间，请保持页面打开并避免同时删除资料。恢复方法包含在 ZIP
        的“恢复说明.txt”中。
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      {done && (
        <Notice tone="success">
          备份已打包并发起下载，请确认浏览器下载完成后妥善保存 ZIP 文件。
        </Notice>
      )}
    </section>
  );
}
