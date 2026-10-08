export type UsageRow = {
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
          {!!r.incomplete_calls && `；${r.incomplete_calls} 次未报告完整分项，以上为已报告部分`}
          {r.unreported_calls > 0 ? `；${r.unreported_calls} 次未报告总用量` : ''}
        </p>
      ))}
    </details>
  );
}
