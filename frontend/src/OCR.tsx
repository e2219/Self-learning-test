import { UsageBreakdown, type UsageRow } from './Usage';
import { newSubmissionId } from './draft';
import { MaterialQuality } from './MaterialQuality';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, json, useRemote } from './api';
import type { Document, Page, Settings } from './types';
import { Loading, MathText, Modal, Notice } from './ui';

type Job = {
  id: string;
  start: number;
  end: number;
  status: string;
  tokens: number;
  token_budget: number;
  usage?: UsageRow[];
  pages: {
    number: number;
    status: string;
    error: string;
    stage: string;
    http_status: number | null;
  }[];
};
const names: Record<string, string> = {
  queued: '等待识别',
  running: '识别中',
  pending: '等待识别',
  ready: '已完成',
  skipped: '复用已有内容',
  partial: '待重试',
  cancelling: '正在停止',
  cancelled: '已停止',
  failed: '识别失败',
};
const stages: Record<string, string> = {
  rendering: '渲染页面，尚未开始 API 请求',
  client_setup: '初始化网络客户端，尚未开始 API 请求',
  requesting: '已进入请求步骤，尚未记录接口响应',
  response_received: '已收到接口响应',
  saving: '正在保存识别结果',
  saved: '识别结果已保存',
  cached: '复用已有内容，本次未调用 API',
};
const running = (job: Job | null) =>
  !!job && ['queued', 'running', 'cancelling'].includes(job.status);

export function DocumentOCR({
  doc,
  start = 1,
  end,
  close,
}: {
  doc: Document;
  start?: number;
  end?: number;
  close: () => void;
}) {
  const [from, setFrom] = useState(start),
    [to, setTo] = useState(end ?? Math.min(start + 4, doc.page_count));
  const actionLock = useRef(false);
  const submission = useRef<{ signature: string; id: string } | null>(null);
  const [budget, setBudget] = useState(0);
  const [force, setForce] = useState(false),
    [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [loaded, setLoaded] = useState(false);
  const [number, setNumber] = useState(start),
    [editing, setEditing] = useState(false),
    [text, setText] = useState('');
  const [inspect, setInspect] = useState(false);
  const [listOffset, setListOffset] = useState(0);
  const [saved, setSaved] = useState('');
  const settings = useRemote<Settings>('/settings');
  const page = useRemote<Page>(`/documents/${doc.id}/pages/${number}`);
  const max = settings.data?.ocr_max_pages ?? 2000;
  useEffect(() => {
    let live = true;
    api<Job | null>(`/documents/${doc.id}/ocr`)
      .then((j) => {
        if (live) {
          setJob(j);
          setBudget(j?.token_budget || 0);
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setLoaded(true);
      });
    return () => {
      live = false;
    };
  }, [doc.id]);
  useEffect(() => {
    if (!running(job)) return;
    let live = true;
    const timer = window.setTimeout(async () => {
      try {
        const updated = await api<Job>(`/ocr/${job!.id}`);
        if (!live) return;
        setJob(updated);
        await page.reload();
      } catch (e) {
        if (live) {
          setError((e as Error).message);
          setJob((j) => (j ? { ...j } : j));
        }
      }
    }, 1800);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [job, page.reload]);
  async function act(path: string, body?: object) {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError('');
    setSaved('');
    try {
      if (path.endsWith('/retry') && job) {
        await api(`/ocr/${job.id}/budget`, json('PUT', { token_budget: budget }));
      }
      if (path === `/documents/${doc.id}/ocr`) {
        const signature = JSON.stringify({ ...body, token_budget: budget });
        if (submission.current?.signature !== signature)
          submission.current = { signature, id: newSubmissionId() };
        body = { ...body, token_budget: budget, submission_id: submission.current.id };
      }
      setJob(await api<Job>(path, json('POST', body)));
      submission.current = null;
      setListOffset(0);
      await page.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      actionLock.current = false;
    }
  }
  function selectPage(value: number) {
    if (value < 1 || value > doc.page_count || !Number.isInteger(value)) return;
    if (editing && !window.confirm('切换页面会放弃未保存的修正，继续吗？')) return;
    setEditing(false);
    setSaved('');
    setNumber(value);
    setInspect(true);
  }
  const done = job?.pages.filter((p) => ['ready', 'skipped'].includes(p.status)).length ?? 0;
  return (
    <Modal title="文字与公式识别" close={close}>
      <p className="ocr-document-name">{doc.name}</p>
      <Notice>
        自动复用正常文字，扫描页、异常文本和待处理表格交给 所选识图模型 读取。需要识图的页面会发送至
        所选识图服务，按 API 用量计费。结果自动保存供出题使用，无需逐页人工确认；图片仍可能被误读。
      </Notice>
      {settings.data && !settings.data.has_vision_key && (
        <Notice>
          <Link to="/settings">先前往设置配置 API Key</Link>
        </Notice>
      )}
      <div className="ocr-range">
        <label>
          识别开始页
          <input
            type="number"
            min={1}
            max={doc.page_count}
            value={from}
            disabled={running(job) || busy}
            onChange={(e) => setFrom(Number(e.target.value))}
          />
        </label>
        <label>
          识别结束页
          <input
            type="number"
            min={from}
            max={doc.page_count}
            value={to}
            disabled={running(job) || busy}
            onChange={(e) => setTo(Number(e.target.value))}
          />
        </label>
        <button
          className="button primary"
          disabled={
            !loaded ||
            busy ||
            running(job) ||
            !settings.data?.has_vision_key ||
            from < 1 ||
            to < from ||
            to > doc.page_count ||
            to - from + 1 > max
          }
          onClick={() => act(`/documents/${doc.id}/ocr`, { start: from, end: to, force })}
        >
          开始识别
        </button>
      </div>
      <p className="field-help">
        使用 PDF 实际页序，每个任务最多 {max}{' '}
        页，后台逐页处理，不会一次上传整本书。默认复用未发现明显异常的 PDF 文本或已有 OCR
        结果；逐字断行等异常文本会识别，手动修正始终保留。
      </p>
      <button
        className="button ghost"
        disabled={running(job) || busy}
        onClick={() => {
          setFrom(1);
          setTo(Math.min(doc.page_count, max));
        }}
      >
        选择整份资料{doc.page_count > max ? `（前 ${max} 页）` : ''}
      </button>
      <label className="ocr-checkbox">
        <input
          type="checkbox"
          checked={force}
          disabled={running(job) || busy}
          onChange={(e) => setForce(e.target.checked)}
        />
        重新识别已有文字的页面（再次计费，不覆盖手动修正）
      </label>
      <label>
        识别 token 预算阈值（0 为不限）
        <input
          type="number"
          min={0}
          max={10000000}
          step={1000}
          value={budget}
          disabled={running(job) || busy}
          onChange={(e) => setBudget(Number(e.target.value))}
        />
      </label>
      <p className="field-help">
        默认关闭识别思考，保留精细图片。达到已报告用量阈值后停止后续页面，当前请求可能超出；调整预算后可重试未完成页。相同图片复用缓存，勾选重新识别会跳过缓存。
      </p>
      {to - from + 1 > max && <Notice tone="error">范围超过 {max} 页，请分批选择。</Notice>}
      {(error || settings.error) && <Notice tone="error">{error || settings.error}</Notice>}
      {job && (
        <section className="ocr-progress" aria-live="polite">
          <strong>
            {names[job.status]} · 第 {job.start}–{job.end} 页 · {done}/{job.pages.length} 页
          </strong>
          <progress aria-label="识别进度" value={done} max={job.pages.length} />
          <p className="field-help">
            关闭窗口后继续在电脑后台识别；重新打开可查看进度。停止会在当前页调用结束后生效。已完成内容保存在本机。
          </p>
          <div className="button-group">
            {running(job) ? (
              <button
                className="button secondary"
                disabled={busy || job.status === 'cancelling'}
                onClick={() => act(`/ocr/${job.id}/cancel`)}
              >
                停止后续识别
              </button>
            ) : (
              ['partial', 'cancelled'].includes(job.status) && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => act(`/ocr/${job.id}/retry`)}
                >
                  重试未完成页
                </button>
              )
            )}
            <span className="muted">本任务累计 {job.tokens.toLocaleString()} tokens</span>
          </div>
          <UsageBreakdown rows={job.usage} />
          {job.tokens === 0 && (
            <p className="field-help">
              0 tokens 表示尚未记录到接口用量，不等于确认未调用或未计费。请查看每页的调用阶段。
            </p>
          )}
          {job.pages.length > 50 && (
            <div className="button-group">
              <button
                className="button ghost"
                disabled={listOffset === 0}
                onClick={() => setListOffset(Math.max(0, listOffset - 50))}
              >
                上一组页面
              </button>
              <span>
                {Math.floor(listOffset / 50) + 1} / {Math.ceil(job.pages.length / 50)}
              </span>
              <button
                className="button ghost"
                disabled={listOffset + 50 >= job.pages.length}
                onClick={() => setListOffset(listOffset + 50)}
              >
                下一组页面
              </button>
            </div>
          )}
          <div className="ocr-page-list">
            {job.pages.slice(listOffset, listOffset + 50).map((p) => (
              <div key={p.number}>
                <button
                  className={`button ${number === p.number ? 'secondary' : 'ghost'}`}
                  onClick={() => selectPage(p.number)}
                >
                  第 {p.number} 页 · {names[p.status]}
                </button>
                {p.stage && (
                  <small>
                    {stages[p.stage] || p.stage}
                    {p.http_status != null ? ` · HTTP ${p.http_status}` : ''}
                  </small>
                )}
                {!p.stage && p.status === 'failed' && (
                  <small>旧任务未记录调用阶段，重试后可查看。</small>
                )}
                {p.error && (
                  <small className={p.status === 'failed' ? 'ocr-page-error' : ''}>{p.error}</small>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
      <button className="button secondary" onClick={() => setInspect(!inspect)}>
        {inspect ? '收起原文对照' : '查看原文与读取结果（可选）'}
      </button>
      {!running(job) && job?.status === 'ready' && (
        <button className="button primary" onClick={close}>
          完成，返回出题
        </button>
      )}
      {inspect && (
        <>
          <div className="preview-toolbar">
            <label className="inline-label">
              核对 PDF 页码
              <input
                type="number"
                min={1}
                max={doc.page_count}
                value={number}
                onChange={(e) => selectPage(Number(e.target.value))}
              />
            </label>
            <a
              className="text-link"
              href={`/api/documents/${doc.id}/file#page=${number}`}
              target="_blank"
              rel="noreferrer"
            >
              打开原 PDF
            </a>
          </div>
          {page.error && <Notice tone="error">{page.error}</Notice>}
          {page.data?.warning && <Notice>{page.data.warning}</Notice>}
          {page.data && (
            <Notice>
              {page.data.text_source === 'manual'
                ? '当前内容来自手动修正，自动识别不会覆盖。需要参考新识别结果时，可使用局部高清识别生成草稿。'
                : page.data.text_source === 'ocr'
                  ? '当前内容来自已保存的 AI 图片识别结果；再次复用不会调用 API。'
                  : '当前内容来自 PDF 自带文本层，尚未通过 AI 图片识别；提取文本不消耗 tokens。'}
              {page.data.text_quality_issue && <p>{page.data.text_quality_issue}</p>}
              {page.data.text_source !== 'manual' && (
                <button
                  className="button secondary"
                  disabled={
                    busy ||
                    running(job) ||
                    !loaded ||
                    page.loading ||
                    !settings.data?.has_vision_key
                  }
                  onClick={() => {
                    if (
                      window.confirm(
                        `将第 ${number} 页图片发送给 所选识图服务 重新识别，按 API 用量计费；成功后替换此页文本，失败保留原内容。继续吗？`,
                      )
                    )
                      void act(`/documents/${doc.id}/ocr`, {
                        start: number,
                        end: number,
                        force: true,
                      });
                  }}
                >
                  仅重新识别当前页（调用 API）
                </button>
              )}
            </Notice>
          )}
          {page.data && !editing && (
            <MaterialQuality
              key={`${doc.id}-${number}`}
              docId={doc.id}
              page={page.data}
              reload={page.reload}
            />
          )}
          <div className="ocr-comparison">
            <div>
              <h3>原始页面</h3>
              <img
                key={number}
                src={`/api/documents/${doc.id}/pages/${number}/image`}
                alt={`PDF 第 ${number} 页原图`}
              />
            </div>
            <div>
              <div className="section-heading">
                <h3>页面文本 {page.data?.edited ? '· 已修正' : ''}</h3>
                {!editing && (
                  <button
                    className="text-link"
                    disabled={page.loading || !page.data}
                    onClick={() => {
                      setText(page.data?.text || '');
                      setEditing(true);
                      setSaved('');
                    }}
                  >
                    修正此页内容
                  </button>
                )}
              </div>
              {editing ? (
                <>
                  <textarea
                    className="page-editor"
                    aria-label="OCR 页面修正"
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={16}
                    maxLength={50000}
                  />
                  <p className="field-help">公式可写成 $P(A)=0.5$；修改后会用于后续出题。</p>
                  <div className="button-group">
                    <button
                      className="button primary"
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true);
                        setError('');
                        try {
                          await api(`/documents/${doc.id}/pages/${number}`, json('PUT', { text }));
                          await page.reload();
                          setEditing(false);
                          setSaved('页面修正已保存。');
                        } catch (e) {
                          setError((e as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      保存修正
                    </button>
                    <button className="button ghost" onClick={() => setEditing(false)}>
                      取消修正
                    </button>
                  </div>
                </>
              ) : page.loading && !page.data ? (
                <Loading />
              ) : (
                <div className="page-text">
                  <MathText>
                    {page.data?.text || '此页尚无可用文字。识别后会在这里显示正文和公式。'}
                  </MathText>
                </div>
              )}
              {saved && <Notice tone="success">{saved}</Notice>}
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
