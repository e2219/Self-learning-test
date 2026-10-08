import { isChoice, type Question } from './types';
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
export type AnswerCheckResult = {
  items: { number: number; status: 'empty' | 'match' | 'different' }[];
  suggested_score: number;
  message: string;
};
export function supportsAutoScore(question: Question) {
  return (
    isChoice(question.type) ||
    question.type === 'true_false' ||
    (question.type === 'fill' && !!question.blanks?.length)
  );
}
export function SavedAnswerResult({
  question,
  result,
  score,
}: {
  question: Question;
  result: AnswerCheckResult;
  score: number | null;
}) {
  return (
    <div className="local-answer-check" role="status">
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
      <p>
        {score === null
          ? '作答已保存，全部未作答，暂不评分。'
          : `作答与评分已保存：${score} / ${question.points} 分`}
        {question.type === 'fill' && score !== null ? '（逐空等分，未填空位不得分）' : ''}
      </p>
      <p className="field-help">
        按标准答案及已列等价答案本地比对，不调用 AI。需要改分时可展开参考答案调整。
      </p>
    </div>
  );
}
