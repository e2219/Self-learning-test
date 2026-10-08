import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, json, useRemote } from './api';
import { Notice, PageHeading } from './ui';
import { Course, Exam, QuestionType, isChoice, typeNames } from './types';

type Result = { page_id: number; title: string; snippet: string; url: string; site: string };
type Preview = {
  id: string;
  title: string;
  text: string;
  url: string;
  authors_url: string;
  license: string;
  license_url: string;
  importable: boolean;
  reason: string;
};
export function WebResources() {
  const courses = useRemote<Course[]>('/courses'),
    exams = useRemote<Exam[]>('/exams'),
    navigate = useNavigate();
  const [site, setSite] = useState('zh'),
    [query, setQuery] = useState('');
  const [results, setResults] = useState<Result[]>([]),
    [searched, setSearched] = useState(false),
    [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [targetExam, setTargetExam] = useState('');
  const [course, setCourse] = useState(''),
    [title, setTitle] = useState(''),
    [stem, setStem] = useState('');
  const [type, setType] = useState<QuestionType>('calculation'),
    [options, setOptions] = useState(['', '', '', '']);
  const [answer, setAnswer] = useState(''),
    [explanation, setExplanation] = useState(''),
    [blanks, setBlanks] = useState(''),
    [points, setPoints] = useState(5),
    [confirmed, setConfirmed] = useState(false);
  const submission = useRef(crypto.randomUUID()),
    lock = useRef(false);
  async function perform(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="OPEN EDUCATIONAL RESOURCES"
        title="资料与考题检索"
        description="检索开放教育资源，查看原文，并将许可明确的题目摘录到历史试卷。全程不调用 AI。"
      />
      <Notice>
        第一版检索中英文维基学院（Wikiversity），不是全网题库。公开可读不代表允许转载；图片、第三方引文及许可不明的页面只提供链接。来源内容也可能有错。
      </Notice>
      <section className="panel form-section">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void perform(async () => {
              setPreview(null);
              setSearched(false);
              setResults([]);
              const data = await api<Result[]>(
                `/web-resources/search?site=${site}&q=${encodeURIComponent(query)}`,
              );
              setResults(data);
              setSearched(true);
            });
          }}
        >
          <div className="form-grid">
            <label>
              检索来源
              <select value={site} onChange={(e) => setSite(e.target.value)}>
                <option value="zh">中文维基学院</option>
                <option value="en">英文 Wikiversity</option>
              </select>
            </label>
            <label>
              关键词
              <input
                required
                maxLength={150}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="如 概率论 或 probability quiz"
              />
            </label>
          </div>
          <button className="button primary" disabled={busy}>
            检索资源
          </button>
        </form>
        {searched && !results.length && <p>没有匹配结果，可更换关键词或尝试英文资源。</p>}
        <div className="resource-results">
          {results.map((r) => (
            <article className="resource-result" key={`${r.site}:${r.page_id}`}>
              <h3>
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title} ↗
                </a>
              </h3>
              <p>{r.snippet}</p>
              <button
                disabled={busy}
                className="button secondary"
                onClick={() =>
                  void perform(async () => {
                    setPreview(null);
                    const p = await api<Preview>(
                      `/web-resources/preview?site=${r.site}&page_id=${r.page_id}`,
                    );
                    setPreview(p);
                    setTitle(p.title.slice(0, 85) + ' · 摘录练习');
                    setStem('');
                    setAnswer('');
                    setExplanation('');
                    setOptions(['', '', '', '']);
                    setBlanks('');
                    setConfirmed(false);
                    submission.current = crypto.randomUUID();
                  })
                }
              >
                查看正文与许可
              </button>
            </article>
          ))}
        </div>
      </section>
      {preview && (
        <section className="panel form-section">
          <h2>{preview.title}</h2>
          <p>
            <a href={preview.url} target="_blank" rel="noreferrer">
              固定版本原文
            </a>{' '}
            ·{' '}
            <a href={preview.authors_url} target="_blank" rel="noreferrer">
              作者与修订记录
            </a>{' '}
            ·{' '}
            {preview.license_url ? (
              <a href={preview.license_url} target="_blank" rel="noreferrer">
                {preview.license}
              </a>
            ) : (
              preview.license
            )}
          </p>
          {!preview.importable && <Notice>{preview.reason}</Notice>}
          <label>
            来源正文（选取所需题目，公式和表格请对照原网页）
            <textarea className="source-excerpt" readOnly rows={14} value={preview.text} />
          </label>
          {preview.importable && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void perform(async () => {
                  const result = await api<{ id: string }>(
                    '/web-resources/import',
                    json('POST', {
                      source_id: preview.id,
                      target_exam_id: targetExam || null,
                      course_id: course,
                      title,
                      question_type: type,
                      confirmed_license: confirmed,
                      submission_id: submission.current,
                      question: {
                        stem,
                        options: isChoice(type) ? options : [],
                        answer:
                          answer ||
                          (type === 'fill' ? '见逐空答案' : '来源未提供答案，请自行核对。'),
                        explanation:
                          explanation ||
                          '手动摘录，未经过 AI 审题；答案由导入者整理，请结合原文核验。',
                        points,
                        knowledge: '开放教育资源摘录',
                        rubric: [],
                        sources: [{ document_id: 'web:' + preview.id, page: 1 }],
                        blanks:
                          type === 'fill'
                            ? blanks
                                .split('\n')
                                .filter((x) => x.trim())
                                .map((answer) => ({ answer: answer.trim(), alternatives: [] }))
                            : [],
                      },
                    }),
                  );
                  navigate(`/exams/${result.id}`);
                });
              }}
            >
              <h3>摘录为练习题</h3>
              <p>
                逐题摘录，可新建试卷或追加到同课程的摘录试卷。题干和选项须摘自本页；答案和解析由你整理，不会自动推断答案或调用模型。
              </p>
              <div className="form-grid">
                <label>
                  所属课程
                  <select
                    required
                    value={course}
                    onChange={(e) => {
                      setCourse(e.target.value);
                      setTargetExam('');
                    }}
                  >
                    <option value="">选择已创建的课程</option>
                    {courses.data?.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  试卷名称
                  <input
                    required
                    maxLength={100}
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>
              </div>
              <label>
                导入目标
                <select value={targetExam} onChange={(e) => setTargetExam(e.target.value)}>
                  <option value="">新建摘录试卷</option>
                  {exams.data
                    ?.filter(
                      (e) =>
                        e.course_id === course &&
                        e.config.origin === 'web_import' &&
                        e.status === 'ready',
                    )
                    .map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.title}
                      </option>
                    ))}
                </select>
              </label>
              <div className="form-grid">
                <label>
                  题型
                  <select value={type} onChange={(e) => setType(e.target.value as QuestionType)}>
                    {Object.entries(typeNames).map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  分值
                  <input
                    required
                    type="number"
                    min="1"
                    max="100"
                    value={points}
                    onChange={(e) => setPoints(Number(e.target.value))}
                  />
                </label>
              </div>
              <label>
                题干摘录
                <textarea
                  required
                  minLength={5}
                  maxLength={12000}
                  rows={6}
                  value={stem}
                  onChange={(e) => setStem(e.target.value)}
                />
              </label>
              {isChoice(type) &&
                options.map((o, i) => (
                  <label key={i}>
                    选项 {'ABCD'[i]}
                    <input
                      required
                      value={o}
                      onChange={(e) =>
                        setOptions(options.map((v, j) => (i === j ? e.target.value : v)))
                      }
                    />
                  </label>
                ))}
              {type === 'fill' ? (
                <label>
                  逐空答案（每行一空；把原文空位换成 [[blank:1]]、[[blank:2]]）
                  <textarea required value={blanks} onChange={(e) => setBlanks(e.target.value)} />
                </label>
              ) : (
                <label>
                  参考答案
                  {isChoice(type)
                    ? '（字母，如 A 或 AC）'
                    : type === 'true_false'
                      ? '（正确 / 错误）'
                      : '（可留空，稍后自行核分）'}
                  <textarea
                    required={isChoice(type) || type === 'true_false'}
                    maxLength={12000}
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                  />
                </label>
              )}
              <label>
                解析（可选）
                <textarea
                  maxLength={20000}
                  value={explanation}
                  onChange={(e) => setExplanation(e.target.value)}
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  required
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                我已查看原文，所选题目无另行声明的转载限制；保留署名、来源与许可，改编按原许可共享。
              </label>
              <button className="button primary" disabled={busy || !confirmed}>
                导入历史试卷（不调用 AI）
              </button>
            </form>
          )}
        </section>
      )}
      {(error || courses.error) && <Notice tone="error">{error || courses.error}</Notice>}
    </>
  );
}
