import { useEffect, useRef, useState } from 'react';
import { api, json } from './api';
import type { Question } from './types';
import { Notice } from './ui';
export function parseBlankAnswers(answer: string, count: number) {
  try {
    const parsed = JSON.parse(answer);
    if (Array.isArray(parsed) && parsed.every((x) => typeof x === 'string'))
      return Array.from({ length: count }, (_, i) => parsed[i] || '');
  } catch {
    /* legacy text remains available in the saved answer */
  }
  return Array(count).fill('') as string[];
}
export function isStructuredAnswer(answer: string) {
  try {
    const value = JSON.parse(answer);
    return Array.isArray(value) && value.every((item) => typeof item === 'string');
  } catch {
    return false;
  }
}
export function displaySavedAnswer(question: Question, answer: string) {
  return question.type === 'fill' && question.blanks?.length && isStructuredAnswer(answer)
    ? parseBlankAnswers(answer, question.blanks.length)
        .map((text, i) => `第 ${i + 1} 空：${text || '未作答'}`)
        .join('；')
    : answer;
}
type Result = {
  items: { number: number; status: 'empty' | 'match' | 'different' }[];
  suggested_score: number;
  all_answered: boolean;
  all_match: boolean;
  message: string;
};
export function AnswerCheck({
  question,
  answer,
  apply,
}: {
  question: Question;
  answer: string;
  apply: (score: number) => void;
}) {
  const [result, setResult] = useState<Result | null>(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const signature = JSON.stringify([
    question.id,
    question.stem,
    question.answer,
    question.blanks,
    answer,
  ]);
  const latest = useRef(signature);
  latest.current = signature;
  useEffect(() => {
    setResult(null);
    setError('');
  }, [signature]);
  const supported =
    question.type === 'choice' ||
    question.type === 'true_false' ||
    (question.type === 'fill' && !!question.blanks?.length);
  if (!supported) return null;
  return (
    <div className="local-answer-check">
      <button
        type="button"
        className="button secondary small"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError('');
          try {
            const checked = await api<Result>(
              `/questions/${question.id}/check-answer`,
              json('POST', {
                answer,
                blanks:
                  question.type === 'fill'
                    ? parseBlankAnswers(answer, question.blanks!.length)
                    : [],
              }),
            );
            if (latest.current === signature) setResult(checked);
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? '核验中…' : '检查答案（不调用 AI）'}
      </button>
      {error && <Notice tone="error">{error}</Notice>}
      {result && (
        <div role="status">
          {result.items.map((item) => (
            <p key={item.number}>
              {question.type === 'fill' ? `第 ${item.number} 空：` : ''}
              {item.status === 'empty'
                ? '未作答'
                : item.status === 'match'
                  ? '与参考答案一致'
                  : '与参考答案不一致，请自行核对'}
            </p>
          ))}
          <p className="field-help">{result.message}</p>
          <p>
            按匹配结果建议得分：{result.suggested_score} / {question.points}
            {question.type === 'fill' ? '（逐空等分）' : ''}
          </p>
          <button
            type="button"
            className="button ghost small"
            onClick={() => apply(result.suggested_score)}
          >
            采用建议分数
          </button>
          <span className="field-help">分数先填入自评分，确认保存后才计入记录。</span>
        </div>
      )}
    </div>
  );
}
