import {
  AnswerCheck,
  parseBlankAnswers,
  isStructuredAnswer,
  displaySavedAnswer,
} from './AnswerCheck';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowRight,
  Bookmark,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Edit3,
  Eye,
  EyeOff,
  FileText,
  History,
  NotebookPen,
  Pause,
  Plus,
  Printer,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { api, date, json, useRemote } from './api';
import type { Course, Exam, Question } from './types';
import { typeNames } from './types';
import { Empty, Loading, MathText, Modal, Notice, PageHeading, Status } from './ui';

export function Exams() {
  const courses = useRemote<Course[]>('/courses');
  const [courseId, setCourseId] = useState(''),
    [search, setSearch] = useState('');
  const exams = useRemote<Exam[]>(`/exams?course_id=${courseId}`);
  const filtered = exams.data?.filter((e) => e.title.toLowerCase().includes(search.toLowerCase()));
  return (
    <>
      <PageHeading
        eyebrow="PRACTICE ARCHIVE"
        title="每一次练习，都被保留。"
        description="回到做过的试卷，继续思考，或再练一次。"
        action={
          <Link className="button primary" to="/generate">
            <Plus size={17} />
            创建测验
          </Link>
        }
      />
      <div className="filter-bar">
        <div className="input-icon">
          <Search size={17} />
          <input
            aria-label="搜索试卷"
            placeholder="搜索试卷名称"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          aria-label="筛选课程"
          value={courseId}
          onChange={(e) => setCourseId(e.target.value)}
        >
          <option value="">全部课程</option>
          {courses.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <span>{filtered?.length || 0} 份试卷</span>
      </div>
      {exams.error && <Notice tone="error">{exams.error}</Notice>}
      {exams.loading ? (
        <Loading />
      ) : filtered?.length ? (
        <div className="exam-grid">
          {filtered.map((e) => (
            <Link className="exam-card" to={`/exams/${e.id}`} key={e.id}>
              <div className="exam-card-top">
                <div className="document-icon">
                  <FileText size={24} />
                </div>
                <Status status={e.status} />
              </div>
              <span className="eyebrow">{e.course_name}</span>
              <h3>{e.title}</h3>
              <div className="exam-card-details">
                <span>{e.question_count} 道题</span>
                <span>{e.total_points} 分</span>
                <span>{date(e.created_at)}</span>
              </div>
              <div className="exam-card-footer">
                <span>
                  {e.ready_count}/{e.question_count} 题已生成
                </span>
                <span>
                  打开试卷
                  <ArrowRight size={15} />
                </span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="panel">
          <Empty
            icon={<FileText size={30} />}
            title={search ? '没有匹配的试卷' : '给知识一次练习的机会'}
            text={
              search ? '试试其他关键词或课程。' : '根据教材生成一份测验，保存、打印或随时复习。'
            }
            action={
              <Link className="button primary" to="/generate">
                创建测验
                <ArrowRight size={16} />
              </Link>
            }
          />
        </div>
      )}
    </>
  );
}

function QuestionEditor({
  question,
  close,
  saved,
}: {
  question: Question;
  close: () => void;
  saved: () => void;
}) {
  const [form, setForm] = useState(question),
    [rubric, setRubric] = useState(question.rubric.join('\n')),
    [blanks, setBlanks] = useState(
      (question.blanks || []).map((b) => [b.answer, ...b.alternatives].join(' | ')).join('\n'),
    ),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  return (
    <Modal title="编辑题目" close={close}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError('');
          try {
            await api(
              `/questions/${question.id}`,
              json('PUT', {
                ...form,
                blanks:
                  question.type === 'fill'
                    ? blanks
                        .split('\n')
                        .filter((s) => s.trim())
                        .map((s) => {
                          const [answer, ...alternatives] = s.split('|').map((v) => v.trim());
                          return { answer, alternatives };
                        })
                    : [],
                rubric: rubric.split('\n').filter((s) => s.trim()),
              }),
            );
            saved();
            close();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Notice>保存修改会清除当前自评分，历史评分记录仍保留。公式支持 $…$ 和 $$…$$。</Notice>
        <label>
          题干
          <textarea
            rows={5}
            required
            minLength={5}
            value={form.stem}
            onChange={(e) => setForm({ ...form, stem: e.target.value })}
          />
        </label>
        {question.type === 'choice' &&
          form.options.map((o, i) => (
            <label key={i}>
              选项 {'ABCD'[i]}
              <textarea
                rows={2}
                value={o}
                required
                onChange={(e) =>
                  setForm({
                    ...form,
                    options: form.options.map((v, j) => (i === j ? e.target.value : v)),
                  })
                }
              />
            </label>
          ))}
        <div className="form-grid">
          <label>
            本题分值
            <input
              type="number"
              min={0.5}
              max={100}
              step={0.5}
              value={form.points}
              onChange={(e) => setForm({ ...form, points: Number(e.target.value) })}
            />
          </label>
          <label>
            知识点
            <input
              value={form.knowledge}
              required
              maxLength={300}
              onChange={(e) => setForm({ ...form, knowledge: e.target.value })}
            />
          </label>
        </div>
        <label>
          参考答案
          {question.type === 'choice' ? (
            <select
              value={form.answer}
              onChange={(e) => setForm({ ...form, answer: e.target.value })}
            >
              {['A', 'B', 'C', 'D'].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          ) : question.type === 'true_false' ? (
            <select
              value={form.answer}
              onChange={(e) => setForm({ ...form, answer: e.target.value })}
            >
              <option>正确</option>
              <option>错误</option>
            </select>
          ) : (
            <textarea
              rows={3}
              required
              value={form.answer}
              onChange={(e) => setForm({ ...form, answer: e.target.value })}
            />
          )}
        </label>
        {question.type === 'fill' && (
          <label>
            逐空答案（每行一空，用 | 分隔等价答案）
            <textarea required value={blanks} onChange={(e) => setBlanks(e.target.value)} />
            <small>
              题干使用 [[blank:1]]、[[blank:2]] 连续编号；保存后按逐空答案生成参考答案。
            </small>
          </label>
        )}
        <label>
          解析
          <textarea
            rows={6}
            required
            value={form.explanation}
            onChange={(e) => setForm({ ...form, explanation: e.target.value })}
          />
        </label>
        <label>
          评分要点（每行一条）
          <textarea rows={3} required value={rubric} onChange={(e) => setRubric(e.target.value)} />
        </label>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="modal-actions">
          <button className="button secondary" type="button" onClick={close}>
            取消
          </button>
          <button className="button primary" type="submit" disabled={busy}>
            <Save size={16} />
            {busy ? '保存中…' : '保存题目'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function AttemptHistory({ question, close }: { question: Question; close: () => void }) {
  const history = useRemote<
    { id: string; score: number; user_answer: string; created_at: string; snapshot: Question }[]
  >(`/questions/${question.id}/attempts`);
  return (
    <Modal title="自行评分记录" close={close}>
      {history.error && <Notice tone="error">{history.error}</Notice>}
      {history.loading ? (
        <Loading />
      ) : history.data?.length ? (
        history.data.map((a) => (
          <div className="attempt" key={a.id}>
            <div className="section-heading">
              <strong>
                {a.score} / {a.snapshot.points} 分
              </strong>
              <span className="muted">{new Date(a.created_at).toLocaleString('zh-CN')}</span>
            </div>
            <p className="attempt-answer">
              {displaySavedAnswer(a.snapshot, a.user_answer) || '纸上作答（未填写文字答案）'}
            </p>
            <details>
              <summary>查看当时的题目与答案</summary>
              <MathText>{a.snapshot.stem}</MathText>
              <MathText>{a.snapshot.answer}</MathText>
            </details>
          </div>
        ))
      ) : (
        <Empty
          icon={<History size={26} />}
          title="还没有评分记录"
          text="每次保存自评分，都会留下当时的题目与答案快照。"
        />
      )}
    </Modal>
  );
}

export function QuestionCard({
  question: q,
  index,
  practice = true,
  editable = false,
  busy = false,
  onChange,
  onAction,
}: {
  question: Question;
  index: number;
  practice?: boolean;
  editable?: boolean;
  busy?: boolean;
  onChange: () => void;
  onAction?: (path: string, method?: string) => Promise<void>;
}) {
  const [revealed, setRevealed] = useState(false),
    [answer, setAnswer] = useState(q.user_answer),
    [score, setScore] = useState<string>(q.self_score === null ? '' : String(q.self_score)),
    [error, setError] = useState(''),
    [message, setMessage] = useState(''),
    [saving, setSaving] = useState(false),
    [editing, setEditing] = useState(false),
    [history, setHistory] = useState(false);
  useEffect(() => {
    setAnswer(q.user_answer);
  }, [q.id, q.user_answer]);
  useEffect(() => {
    setScore(q.self_score === null ? '' : String(q.self_score));
  }, [q.id, q.self_score]);
  useEffect(() => {
    setRevealed(false);
  }, [q.stem]);
  async function save(payload: Record<string, unknown>) {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      await api(`/questions/${q.id}/progress`, json('PATCH', payload));
      setMessage('已保存');
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const complete = q.status === 'ready';
  return (
    <article className="question-card" id={`question-${q.id}`}>
      <div className="question-heading">
        <div className="question-label">
          <span className="question-number">{String(index).padStart(2, '0')}</span>
          <span className="badge type-badge">{typeNames[q.type]}</span>
          <span className="question-points">{q.points} 分</span>
          {q.self_score !== null && (
            <span className="badge score-badge">自评 {q.self_score} 分</span>
          )}
        </div>
        <div className="question-tools">
          {complete && (
            <>
              <button
                className={`icon-button ${q.is_favorite ? 'marked' : ''}`}
                title="收藏题目"
                aria-label={q.is_favorite ? '取消收藏' : '收藏题目'}
                disabled={saving}
                onClick={() => void save({ is_favorite: !q.is_favorite })}
              >
                <Bookmark size={17} fill={q.is_favorite ? 'currentColor' : 'none'} />
              </button>
              <button
                className={`icon-button ${q.is_wrong ? 'wrong-marked' : ''}`}
                title={q.is_wrong ? '移出错题本' : '加入错题本'}
                aria-label={q.is_wrong ? '移出错题本' : '加入错题本'}
                disabled={saving}
                onClick={() => void save({ is_wrong: !q.is_wrong })}
              >
                <NotebookPen size={17} />
              </button>
            </>
          )}
          {editable && !busy && (
            <>
              <button
                className="icon-button"
                aria-label="编辑题目"
                title="编辑题目"
                disabled={!q.stem}
                onClick={() => setEditing(true)}
              >
                <Edit3 size={16} />
              </button>
              <button
                className="icon-button"
                aria-label="重新生成此题"
                title="重新生成此题"
                onClick={() => {
                  if (
                    window.confirm(
                      '重新生成会替换此题，并清除当前作答与评分。历史评分快照会保留，继续吗？',
                    )
                  )
                    void onAction?.(`/questions/${q.id}/regenerate`);
                }}
              >
                <RefreshCw size={16} />
              </button>
              <button
                className="icon-button"
                aria-label="删除题目"
                title="删除题目"
                onClick={() => {
                  if (window.confirm('确认删除此题及其学习记录？'))
                    void onAction?.(`/questions/${q.id}`, 'DELETE');
                }}
              >
                <Trash2 size={16} />
              </button>
            </>
          )}
        </div>
      </div>
      {q.exam_title && (
        <Link className="question-origin" to={`/exams/${q.exam_id}`}>
          {q.course_name} · {q.exam_title}
          <ChevronRight size={13} />
        </Link>
      )}
      {q.error && <Notice tone="error">{q.error}</Notice>}
      {complete && (
        <small className="muted">
          {q.review?.status === 'passed'
            ? '已通过 AI 独立审题，仍建议人工核对'
            : '此题尚无独立审题记录'}
        </small>
      )}
      {!complete && !q.stem ? (
        <div className="question-pending">
          {q.status === 'generating' ? (
            <>
              <Loading label="AI 正在出题与校验…" />
              <p>正在独立解题并核对解析；未通过时自动修订，每题最多尝试 3 次。</p>
            </>
          ) : (
            <>
              <Status status={q.status} />
              <p>
                {q.status === 'failed'
                  ? '点击试卷上方“继续 / 重试”恢复生成。'
                  : '此题完成后会自动显示，无需停留在这个页面。'}
              </p>
            </>
          )}
        </div>
      ) : (
        <>
          <MathText className="question-stem">{q.stem}</MathText>
          {q.options.length > 0 && (
            <div className="question-options">
              {q.options.map((option, i) => (
                <button
                  type="button"
                  key={i}
                  className={`option ${practice && answer === 'ABCD'[i] ? 'chosen' : ''}`}
                  onClick={() => {
                    if (practice && complete) setAnswer('ABCD'[i]);
                  }}
                  disabled={!practice || !complete}
                >
                  <span>{'ABCD'[i]}</span>
                  <MathText>{option}</MathText>
                </button>
              ))}
            </div>
          )}
          {!complete && (
            <Notice>
              上方保留的是上一次题目内容。生成完成后会替换；若重试失败，可以编辑并保存以恢复旧题。
            </Notice>
          )}
          {practice && complete && (
            <div className="answer-area">
              {q.type === 'true_false' ? (
                <div className="true-false-options">
                  {['正确', '错误'].map((v) => (
                    <button
                      key={v}
                      className={`button ${answer === v ? 'primary' : 'secondary'}`}
                      onClick={() => setAnswer(v)}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              ) : q.type === 'fill' && !!q.blanks?.length ? (
                <div>
                  {q.user_answer && !isStructuredAnswer(q.user_answer) && (
                    <Notice>
                      以前保存的整段作答：{q.user_answer}
                      。请逐空填写后核验；保存新作答会替换这段文字。
                    </Notice>
                  )}
                  <div className="form-grid">
                    {q.blanks.map((_, i) => (
                      <label key={i}>
                        第 {i + 1} 空
                        <input
                          aria-label={`第 ${i + 1} 空答案`}
                          value={parseBlankAnswers(answer, q.blanks!.length)[i]}
                          onChange={(e) => {
                            const next = parseBlankAnswers(answer, q.blanks!.length);
                            next[i] = e.target.value;
                            setAnswer(JSON.stringify(next));
                          }}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              ) : (
                q.type !== 'choice' && (
                  <label>
                    我的作答 <span className="muted">（也可以写在纸上）</span>
                    <textarea
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      rows={3}
                      placeholder="记录你的答案或思路；复杂公式和证明可以在纸上完成。"
                    />
                  </label>
                )
              )}
              <AnswerCheck
                question={q}
                answer={answer}
                apply={(value) => {
                  setScore(String(value));
                  setRevealed(true);
                }}
              />
              <div className="answer-actions">
                {(q.self_score !== null || q.user_answer) && (
                  <button
                    className="button ghost small"
                    disabled={saving}
                    onClick={async () => {
                      await save({ user_answer: '', self_score: null });
                      setRevealed(false);
                    }}
                  >
                    <RefreshCw size={14} />
                    重新作答
                  </button>
                )}
                <button
                  className="button secondary small"
                  disabled={saving}
                  onClick={() => void save({ user_answer: answer })}
                >
                  <Save size={14} />
                  保存作答
                </button>
                <span className="field-help">仅点击保存后记录到本机</span>
              </div>
            </div>
          )}
          {complete && (
            <>
              <div className="question-bottom">
                <button className="text-link" onClick={() => setRevealed(!revealed)}>
                  {revealed ? <EyeOff size={16} /> : <Eye size={16} />}{' '}
                  {revealed ? '收起参考答案' : '查看参考答案与解析'}
                </button>
                <MathText className="knowledge-label">{q.knowledge}</MathText>
              </div>
              {revealed && (
                <div className="solution">
                  <div className="solution-label">参考答案</div>
                  <MathText>{q.answer}</MathText>
                  <div className="solution-label">解题思路</div>
                  <MathText>{q.explanation}</MathText>
                  <div className="solution-label">评分要点</div>
                  <ul>
                    {q.rubric.map((r, i) => (
                      <li key={i}>
                        <MathText>{r}</MathText>
                      </li>
                    ))}
                  </ul>
                  <div className="sources">
                    <BookOpen size={14} />
                    <div>
                      知识依据：
                      {q.sources.map((s, i) => (
                        <a
                          key={i}
                          href={`/api/documents/${s.document_id}/file#page=${s.page}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {s.name} · PDF 第 {s.page} 页
                        </a>
                      ))}
                      <small>AI 新编题；引用为知识依据。请结合教材核验解答。</small>
                    </div>
                  </div>
                  {practice && (
                    <div className="self-score">
                      <label>
                        本题自评分
                        <input
                          aria-label="本题自评分"
                          type="number"
                          min={0}
                          max={q.points}
                          step="any"
                          value={score}
                          onChange={(e) => setScore(e.target.value)}
                        />
                        <span>/ {q.points}</span>
                      </label>
                      <button
                        className="button primary small"
                        disabled={
                          saving || score === '' || Number(score) > q.points || Number(score) < 0
                        }
                        onClick={() =>
                          void save({ user_answer: answer, self_score: Number(score) })
                        }
                      >
                        <Check size={15} />
                        保存评分
                      </button>
                      <button className="text-link" onClick={() => setHistory(true)}>
                        <History size={15} />
                        历史
                      </button>
                      <p>未满分的题目自动加入错题本，满分后自动移出。</p>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {message && (
        <div className="save-message" role="status">
          <Check size={13} />
          {message}
        </div>
      )}
      {editing && <QuestionEditor question={q} close={() => setEditing(false)} saved={onChange} />}
      {history && <AttemptHistory question={q} close={() => setHistory(false)} />}
    </article>
  );
}

export function ExamPage() {
  const { examId } = useParams(),
    navigate = useNavigate();
  const exam = useRemote<Exam>(`/exams/${examId}`);
  const [mode, setMode] = useState('practice'),
    [error, setError] = useState(''),
    [actionBusy, setActionBusy] = useState(false),
    [info, setInfo] = useState('');
  const data = exam.data;
  const generating =
    !!data &&
    (data.status === 'queued' ||
      data.status === 'generating' ||
      data.questions.some((q) => q.status === 'generating'));
  useEffect(() => {
    if (!generating) return;
    const timer = window.setInterval(() => void exam.reload(), 2500);
    return () => window.clearInterval(timer);
  }, [generating, exam.reload]);
  async function action(path: string, method = 'POST') {
    setActionBusy(true);
    setError('');
    try {
      await api(path, json(method));
      await exam.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy(false);
    }
  }
  if (exam.loading) return <Loading />;
  if (!data) return <Notice tone="error">{exam.error || '找不到试卷。'}</Notice>;
  const ready = data.questions.filter((q) => q.status === 'ready').length;
  const scored = data.questions.filter((q) => q.self_score !== null);
  return (
    <>
      <Link className="back-link" to="/exams">
        <ChevronLeft size={15} />
        历史试卷
      </Link>
      <PageHeading
        eyebrow={data.course_name}
        title={data.title}
        description={`${data.questions.length} 道题 · ${data.total_points} 分 · ${data.config.difficulty} · ${date(data.created_at)}`}
        action={
          <div className="button-group">
            <Link
              target="_blank"
              className={`button secondary ${ready ? '' : 'disabled'}`}
              to={`/exams/${examId}/print`}
            >
              <Printer size={16} />
              打印试卷
            </Link>
            <Link
              target="_blank"
              className={`button secondary ${ready ? '' : 'disabled'}`}
              to={`/exams/${examId}/print?answers=1`}
            >
              打印答案
            </Link>
          </div>
        }
      />
      {(error || exam.error) && <Notice tone="error">{error || exam.error}</Notice>}
      {info && <Notice>{info}</Notice>}
      {data.error && <Notice>{data.error}</Notice>}
      {data.coverage && (
        <details className="panel">
          <summary>
            考点覆盖情况 · 规划用量 {data.planning_tokens ?? 0} tokens（与出题用量分开）
          </summary>
          <p className="field-help">
            以下统计按分配表和已完成题目计算；AI
            审题不能保证事实完全正确。删除题目后原分配仍保留供核对。
          </p>
          {data.coverage.map((t, i) => (
            <p key={i}>
              {t.title}：分配 {t.planned} 题，完成 {t.completed} 题
              {t.planned === 0 ? ' · 尚未覆盖' : ''}
            </p>
          ))}
        </details>
      )}
      <div className="exam-progress panel">
        <div className="progress-info">
          <Status status={data.status} />
          <span>
            已生成 {ready} / {data.questions.length} 题
          </span>
          <span className="muted">
            <Clock3 size={14} />
            建议 {data.config.duration} 分钟
          </span>
        </div>
        <div className="progress-track">
          <div style={{ width: `${(ready / data.questions.length) * 100}%` }} />
        </div>
        {generating ? (
          <button
            className="button ghost small"
            disabled={actionBusy || data.status === 'paused'}
            onClick={async () => {
              await action(`/exams/${examId}/pause`);
              setInfo('当前 API 调用结束后暂停，已完成题目会保留。');
            }}
          >
            <Pause size={14} />
            暂停后续生成
          </button>
        ) : ready < data.questions.length ? (
          <button
            className="button primary small"
            disabled={actionBusy}
            onClick={() => void action(`/exams/${examId}/retry`)}
          >
            <RefreshCw size={14} />
            继续 / 重试
          </button>
        ) : (
          <span className="muted">答案仅供学习参考</span>
        )}
      </div>
      <div className="exam-workspace">
        <section>
          <div className="exam-toolbar">
            <div className="segmented">
              <button
                className={mode === 'practice' ? 'selected' : ''}
                onClick={() => setMode('practice')}
              >
                <NotebookPen size={16} />
                在线练习
              </button>
              <button
                className={mode === 'preview' ? 'selected' : ''}
                onClick={() => setMode('preview')}
              >
                <Eye size={16} />
                试卷预览
              </button>
            </div>
            <span className="muted">先思考，再展开答案</span>
          </div>
          {data.questions.map((q, i) => (
            <QuestionCard
              key={q.id}
              question={q}
              index={i + 1}
              practice={mode === 'practice'}
              editable
              busy={generating || actionBusy}
              onChange={() => void exam.reload()}
              onAction={action}
            />
          ))}
        </section>
        <aside className="exam-aside">
          <div className="panel answer-sheet">
            <span className="eyebrow">YOUR PROGRESS</span>
            <h3>练习进度</h3>
            <div className="score-total">
              <strong>{scored.reduce((n, q) => n + (q.self_score || 0), 0)}</strong>
              <span>/ {data.total_points} 分</span>
            </div>
            <p>
              已自评 {scored.length} / {data.questions.length} 题
            </p>
            <div className="question-map">
              {data.questions.map((q, i) => (
                <a
                  key={q.id}
                  className={
                    q.self_score !== null ? 'scored' : q.status !== 'ready' ? 'pending' : ''
                  }
                  href={`#question-${q.id}`}
                >
                  {i + 1}
                </a>
              ))}
            </div>
            <div className="map-legend">
              <span>
                <i />
                未评分
              </span>
              <span>
                <i className="scored" />
                已评分
              </span>
            </div>
          </div>
          <div className="quiet-note">
            <NotebookPen size={19} />
            <span>计算和证明可以先在纸上完成，对照解析后自行评分。</span>
          </div>
          <div className="exam-admin">
            <span>已记录模型用量：{data.tokens.toLocaleString()} tokens</span>
            <button
              className="text-link muted"
              disabled={generating || actionBusy}
              onClick={async () => {
                if (!window.confirm('删除这份试卷及其全部学习记录？')) return;
                try {
                  await api(`/exams/${examId}`, json('DELETE'));
                  navigate('/exams');
                } catch (err) {
                  setError((err as Error).message);
                }
              }}
            >
              <Trash2 size={14} />
              删除试卷
            </button>
          </div>
        </aside>
      </div>
    </>
  );
}

export function PrintPage() {
  const { examId } = useParams(),
    [params] = useSearchParams();
  const answers = params.get('answers') === '1',
    exam = useRemote<Exam>(`/exams/${examId}`);
  if (exam.loading) return <Loading />;
  if (!exam.data) return <Notice tone="error">{exam.error}</Notice>;
  const data = exam.data,
    questions = data.questions.filter((q) => q.status === 'ready');
  return (
    <>
      <div className="print-controls">
        <Link className="back-link" to={`/exams/${examId}`}>
          <ChevronLeft size={16} />
          返回试卷
        </Link>
        <span>{answers ? '参考答案与评分要点' : '学生试卷 · 不包含答案'}</span>
        <button
          className="button primary"
          disabled={!questions.length}
          onClick={() => window.print()}
        >
          <Printer size={16} />
          打印 / 保存 PDF
        </button>
      </div>
      {questions.length < data.questions.length && (
        <div className="print-controls">
          <Notice>
            有 {data.questions.length - questions.length}{' '}
            道题未完成。打印仅包含已完成题目，分值已按实际题目计算。
          </Notice>
        </div>
      )}
      <div className="print-paper">
        <header className="print-header">
          <div>
            {data.course_name} · {answers ? '参考答案' : '课程练习'}
          </div>
          <h1>
            {data.title}
            {answers ? ' · 参考答案' : ''}
          </h1>
          <p>
            共 {questions.length} 题 · 满分 {questions.reduce((n, q) => n + q.points, 0)} 分 ·
            建议用时 {data.config.duration} 分钟
          </p>
          {!answers && (
            <div className="print-name">
              姓名：________________　日期：________________　得分：________
            </div>
          )}
        </header>
        {questions.map((q, i) => (
          <section className="print-question" key={q.id}>
            <div className="print-question-heading">
              {i + 1}. {typeNames[q.type]}（{q.points} 分）
            </div>
            <MathText>{q.stem}</MathText>
            {q.options.map((o, j) => (
              <div className="print-option" key={j}>
                <span>{'ABCD'[j]}.</span>
                <MathText>{o}</MathText>
              </div>
            ))}
            {answers ? (
              <div className="print-solution">
                <strong>参考答案</strong>
                <MathText>{q.answer}</MathText>
                <strong>解析</strong>
                <MathText>{q.explanation}</MathText>
                <strong>评分要点</strong>
                <ul>
                  {q.rubric.map((r, j) => (
                    <li key={j}>
                      <MathText>{r}</MathText>
                    </li>
                  ))}
                </ul>
                <p className="print-citation">
                  知识依据：{q.sources.map((s) => `${s.name} 第 ${s.page} 页`).join('；')}（PDF
                  页码）
                </p>
              </div>
            ) : (
              <div className={`writing-space writing-${q.type}`}>
                {q.type === 'choice' || q.type === 'true_false' ? '作答：____________' : ''}
              </div>
            )}
          </section>
        ))}
        <footer className="print-footer">
          知习 · {answers ? 'AI 参考解答，请结合教材核验。' : '认真思考，写下你的推导过程。'}
        </footer>
      </div>
    </>
  );
}

export function Review() {
  const courses = useRemote<Course[]>('/courses'),
    [courseId, setCourseId] = useState(''),
    [mode, setMode] = useState('wrong');
  const review = useRemote<Question[]>(`/review?course_id=${courseId}&mode=${mode}`);
  return (
    <>
      <PageHeading
        eyebrow="REVIEW & REFLECT"
        title="把薄弱点，变成下一次进步。"
        description="重做一道错题，理清一个概念。理解就这样慢慢积累。"
      />
      <div className="filter-bar">
        <div className="segmented">
          <button className={mode === 'wrong' ? 'selected' : ''} onClick={() => setMode('wrong')}>
            <NotebookPen size={16} />
            错题本
          </button>
          <button
            className={mode === 'favorites' ? 'selected' : ''}
            onClick={() => setMode('favorites')}
          >
            <Bookmark size={16} />
            我的收藏
          </button>
        </div>
        <select
          aria-label="筛选课程"
          value={courseId}
          onChange={(e) => setCourseId(e.target.value)}
        >
          <option value="">全部课程</option>
          {courses.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <span>{review.data?.length || 0} 道题</span>
      </div>
      {review.error && <Notice tone="error">{review.error}</Notice>}
      {review.loading ? (
        <Loading />
      ) : review.data?.length ? (
        <div className="review-list">
          {review.data.map((q, i) => (
            <QuestionCard
              key={q.id}
              question={q}
              index={i + 1}
              onChange={() => void review.reload()}
            />
          ))}
        </div>
      ) : (
        <div className="panel">
          <Empty
            icon={mode === 'wrong' ? <NotebookPen size={30} /> : <Bookmark size={30} />}
            title={mode === 'wrong' ? '暂时没有待巩固的错题' : '留住值得再想一次的题'}
            text={
              mode === 'wrong'
                ? '自行评分未满分的题目会进入这里，也可以在试卷中手动标记。'
                : '在试卷中点击收藏图标，把值得反复练习的题目放在这里。'
            }
            action={
              <Link className="button primary" to="/exams">
                去看看试卷
                <ArrowRight size={16} />
              </Link>
            }
          />
        </div>
      )}
      <div className="quiet-note">
        <Sparkles size={17} />
        <span>第一版支持重做原题。之后可继续扩展同知识点变式题与复习计划。</span>
      </div>
    </>
  );
}
