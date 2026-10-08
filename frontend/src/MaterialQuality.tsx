import { useState } from 'react';
import { api, json } from './api';
import type { Page } from './types';
import { Notice } from './ui';

export function MaterialQuality({
  docId,
  page,
  reload,
}: {
  docId: string;
  page: Page;
  reload: () => void;
}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [region, setRegion] = useState({ x: 0, y: 0, width: 100, height: 50 });
  const [draft, setDraft] = useState<{ text: string; tokens: number; message: string } | null>(
    null,
  );
  async function mark(confirmed: boolean) {
    setBusy(true);
    setError('');
    try {
      await api(
        `/documents/${docId}/pages/${page.number}/table-review`,
        json('PUT', { text_hash: page.text_hash, confirmed }),
      );
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="material-quality">
      {page.has_table ? (
        <>
          <Notice>
            {page.auto_usable
              ? '此页已通过图片读取及表格结构检查，可直接用于出题；数据准确性仍可对照原页检查。'
              : page.needs_review
                ? '此页含表格，核对前不用于出题。请对照原页检查行列、数据、单位和脚注。'
                : '此表格页已人工确认；再次修改或识别后需要重新核对。'}
          </Notice>
          {page.table_issues?.map((issue, i) => (
            <Notice key={i} tone="error">
              {issue}
            </Notice>
          ))}
          <button
            type="button"
            className="button secondary"
            disabled={busy || !!page.table_issues?.length}
            onClick={() => mark(!!page.needs_review)}
          >
            {page.auto_usable
              ? '发现问题，标为待核对'
              : page.needs_review
                ? '已对照原页核对表格'
                : '撤销表格确认'}
          </button>
        </>
      ) : (
        <button type="button" className="text-link" disabled={busy} onClick={() => mark(false)}>
          原页有表格？标为待核对
        </button>
      )}
      <details>
        <summary>局部高清识别（再次调用 API）</summary>
        <p className="field-help">
          按页面百分比填写矩形范围，左上角为
          0%。选择时包含完整表头、单位和脚注。只生成草稿，请复制需要的部分到“修正此页内容”。
        </p>
        <div style={{ position: 'relative', maxWidth: 400, margin: '1rem auto' }}>
          <img
            src={`/api/documents/${docId}/pages/${page.number}/image`}
            alt="局部识别范围预览"
            style={{ width: '100%', display: 'block' }}
          />
          <div
            style={{
              position: 'absolute',
              left: `${region.x}%`,
              top: `${region.y}%`,
              width: `${region.width}%`,
              height: `${region.height}%`,
              border: '2px solid #315d50',
              background: '#315d5022',
              pointerEvents: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>
        <div className="form-grid">
          {(['x', 'y', 'width', 'height'] as const).map((key, i) => (
            <label key={key}>
              {['左侧起点 %', '顶部起点 %', '宽度 %', '高度 %'][i]}
              <input
                type="number"
                min={i < 2 ? 0 : 5}
                max={100}
                value={region[key]}
                onChange={(e) => setRegion({ ...region, [key]: Number(e.target.value) })}
              />
            </label>
          ))}
        </div>
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError('');
            setDraft(null);
            try {
              setDraft(
                await api(
                  `/documents/${docId}/pages/${page.number}/recognize-region`,
                  json(
                    'POST',
                    Object.fromEntries(Object.entries(region).map(([k, v]) => [k, v / 100])),
                  ),
                ),
              );
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? '处理中…' : '识别选定区域'}
        </button>
        {draft && (
          <>
            <p>
              {draft.message} 本次 {draft.tokens} tokens。
            </p>
            <textarea aria-label="局部识别草稿" readOnly rows={10} value={draft.text} />
          </>
        )}
      </details>
      {error && <Notice tone="error">{error}</Notice>}
    </div>
  );
}
