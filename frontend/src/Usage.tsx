import { useState } from 'react';
import { api } from './api';
export type UsageRow = {
  estimated_usd_min?: number | null;
  estimated_usd_max?: number | null;
  unpriced_calls?: number;
  failed_calls?: number;
  requested_models?: string | null;
  thinking_modes?: string | null;
  stage: string;
  models?: string | null;
  reasoning_tokens?: number | null;
  incomplete_calls?: number;
  calls: number;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  total_tokens: number | null;
  unreported_calls: number;
  retry_calls: number;
};
const modes: Record<string, string> = {
  enabled: '开启',
  disabled: '关闭',
  provider_default: '服务商默认',
};
const outcomes: Record<string, string> = {
  started: '调用中',
  received: '收到响应',
  validated: '已通过校验',
  rejected: '未通过校验',
  http_error: '接口错误',
  invalid_json: '响应格式错误',
  truncated: '输出截断',
  timeout: '超时',
  network_error: '网络错误',
  client_error: '客户端错误',
  interrupted: '服务中断，结果未知',
};
const labels: Record<string, string> = {
  generation_batch: '两题合并生成',
  generation: '生成题目',
  blind_review: '独立解题审查',
  consistency_review: '答案一致性审查',
  planning: '考点规划',
  combined_review: '单次合并审题',
  source_image_review: '原图独立复核',
  explanation: '补充详解',
  explanation_review: '详解核验',
};
export function UsageBreakdown({ rows = [] }: { rows?: UsageRow[] }) {
  if (!rows.length) return null;
  return (
    <details>
      <summary>查看 API 用量分布</summary>
      <p className="field-help">
        仅统计更新后接口返回的用量，未知不代表
        0；金额取决于模型和缓存命中的实际计价。输入包含图片与指令，输出包含接口报告的思考用量；缓存命中是输入的一部分，思考是输出的一部分，不要重复相加。
      </p>
      {rows.map((r) => (
        <p key={r.stage}>
          {r.stage.startsWith('ocr_page:')
            ? `第 ${r.stage.split(':')[1]} 页识别`
            : r.stage.startsWith('ocr_region:')
              ? `第 ${r.stage.split(':')[1]} 页局部识别`
              : labels[r.stage] || r.stage}
          ：{r.calls} 次（重试 {r.retry_calls} 次），输入 {r.input_tokens ?? '未报告'} / 输出{' '}
          {r.output_tokens ?? '未报告'} / 缓存命中 {r.cached_tokens ?? '未报告'} / 合计{' '}
          {r.total_tokens ?? '未报告'} tokens · 思考 {r.reasoning_tokens ?? '未报告'} · 实际模型{' '}
          {r.models || '未报告'}
          {r.requested_models && ` · 请求模型 ${r.requested_models}`}
          {r.thinking_modes && ` · 思考设置 ${r.thinking_modes}`}
          {!!r.failed_calls && ` · 失败/拒收 ${r.failed_calls} 次`}
          {r.estimated_usd_min != null &&
            ` · 已知部分参考费用 $${r.estimated_usd_min.toFixed(6)}–$${r.estimated_usd_max?.toFixed(6)}`}
          {!!r.unpriced_calls && ` · ${r.unpriced_calls} 次无法估价`}
          {!!r.incomplete_calls && `；${r.incomplete_calls} 次未报告完整分项，以上为已报告部分`}
          {r.unreported_calls > 0 ? `；${r.unreported_calls} 次未报告总用量` : ''}
        </p>
      ))}
    </details>
  );
}

type Ledger = {
  rows: UsageRow[];
  undated_calls: number;
  price_version: string;
  recent: {
    id: number;
    created_at: string | null;
    stage: string;
    requested_model: string | null;
    model: string;
    thinking: string | null;
    outcome: string | null;
    error_code: string | null;
    total_tokens: number | null;
    request_id: string | null;
  }[];
};
export function UsageLedger() {
  const [data, setData] = useState<Ledger | null>(null);
  const [start, setStart] = useState(''),
    [end, setEnd] = useState('');
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  async function load() {
    setBusy(true);
    setError('');
    try {
      setData(await api<Ledger>(`/usage?${new URLSearchParams({ start, end })}`));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details
      className="panel form-section"
      onToggle={(e) => {
        if (e.currentTarget.open && !data && !busy) void load();
      }}
    >
      <summary>API 用量与参考费用</summary>
      <p className="field-help">
        请求记录保存在本机，删除试卷后仍保留。日期按
        UTC；失败且未返回用量的请求不按零费用计算。这里只读取本地记录，不调用 AI。
      </p>
      <label>
        开始日期（UTC）
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
      </label>
      <label>
        结束日期（UTC）
        <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
      </label>
      <button
        type="button"
        className="button secondary"
        disabled={busy}
        onClick={() => void load()}
      >
        {busy ? '读取中…' : '查询用量'}
      </button>
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <p>
            共 {data.rows.reduce((n, r) => n + r.calls, 0)} 次请求；已报告{' '}
            {data.rows.reduce((n, r) => n + (r.total_tokens ?? 0), 0).toLocaleString()} tokens。
          </p>
          <p>
            {data.rows.some((r) => r.estimated_usd_min != null) ? (
              <>
                可估价部分：$
                {data.rows.reduce((n, r) => n + (r.estimated_usd_min ?? 0), 0).toFixed(6)}–$
                {data.rows.reduce((n, r) => n + (r.estimated_usd_max ?? 0), 0).toFixed(6)}；
              </>
            ) : (
              '暂无可估价记录；'
            )}
            {data.rows.reduce((n, r) => n + (r.unpriced_calls ?? 0), 0)} 次无法估价。
          </p>
          <p className="field-help">
            内置价格参考：{data.price_version}
            。按请求保存价格快照；区间覆盖高峰/非高峰，实际以账单为准。旧记录 {
              data.undated_calls
            }{' '}
            次没有日期，筛选日期时不计入；不补造历史价格。
          </p>
          <UsageBreakdown rows={data.rows} />
          <details>
            <summary>最近 50 次请求</summary>
            {data.recent.map((r) => (
              <p key={r.id} style={{ overflowWrap: 'anywhere' }}>
                {r.created_at || '历史日期未知'} · {labels[r.stage] || r.stage} ·{' '}
                {outcomes[r.outcome || ''] || r.outcome || '历史状态未知'}
                {r.error_code && ` (${r.error_code})`}
                <br />
                请求 {r.requested_model || '未知'} → 返回 {r.model || '未知'} · 思考{' '}
                {modes[r.thinking || ''] || r.thinking || '未知'} · {r.total_tokens ?? '未报告'}{' '}
                tokens
                {r.request_id && <> · 请求编号 {r.request_id}</>}
              </p>
            ))}
          </details>
        </>
      )}
    </details>
  );
}
