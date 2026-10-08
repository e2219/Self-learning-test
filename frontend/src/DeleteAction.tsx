import { useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { api, json } from './api';

export function DeleteAction({
  path,
  label,
  name,
  warning,
  disabled = false,
  deleted,
  failed,
}: {
  path: string;
  label: string;
  name: string;
  warning: string;
  disabled?: boolean;
  deleted: () => void | Promise<void>;
  failed: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  return (
    <button
      type="button"
      className="button ghost danger"
      disabled={disabled || busy}
      aria-label={`${label}：${name}`}
      title={disabled ? '试卷正在生成，请打开试卷暂停，等待当前调用结束后再删除。' : label}
      onClick={async () => {
        if (lock.current || !window.confirm(`确认${label}「${name}」？${warning}此操作不可撤销。`))
          return;
        lock.current = true;
        setBusy(true);
        failed('');
        try {
          await api(path, json('DELETE'));
          await deleted();
        } catch (error) {
          failed((error as Error).message);
        } finally {
          lock.current = false;
          setBusy(false);
        }
      }}
    >
      <Trash2 size={16} />
      {busy ? '删除中…' : label}
    </button>
  );
}
