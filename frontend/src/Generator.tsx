import { Blueprint, type DraftHandle } from './Blueprint';
import { localDraftKey, needsPlanning, readLocalDraft, draftSnapshot } from './draft';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronLeft,
  Eye,
  FileText,
  Shuffle,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react';
import { DocumentOCR } from './OCR';
import { api, json, useRemote } from './api';
import type {
  Course,
  Document,
  Exam,
  ExamConfig,
  ExamPlan,
  QuestionType,
  Settings,
  SourceRange,
} from './types';
import { typeNames } from './types';
import { Empty, Loading, Modal, Notice, PageHeading } from './ui';

const initialRules = (Object.keys(typeNames) as QuestionType[]).map((type) => ({
  type,
  count: type === 'choice' ? 3 : type === 'calculation' ? 2 : 0,
  points: type === 'proof' || type === 'calculation' ? 10 : 5,
}));

export function Generator() {
  const [params] = useSearchParams(),
    navigate = useNavigate();
  const draftRef = useRef<DraftHandle>(null),
    submitting = useRef(false);
  const [latest, setLatest] = useState<ExamPlan | null>(null),
    [localRecovery, setLocalRecovery] = useState<ReturnType<typeof readLocalDraft>>(null);
  const courses = useRemote<Course[]>('/courses'),
    settings = useRemote<Settings>('/settings');
  const [courseId, setCourseId] = useState(params.get('course') || ''),
    [docs, setDocs] = useState<Document[]>([]),
    [ranges, setRanges] = useState<SourceRange[]>([]);
  const [title, setTitle] = useState(''),
    [mode, setMode] = useState('custom'),
    [readingMode, setReadingMode] = useState<'study' | 'vision'>('study'),
    [reviewMode, setReviewMode] = useState<'full' | 'adaptive'>('full'),
    [rules, setRules] = useState(initialRules),
    [randomCount, setRandomCount] = useState(10),
    [difficulty, setDifficulty] = useState('基础巩固'),
    [focus, setFocus] = useState(''),
    [instructions, setInstructions] = useState(''),
    [maxAttempts, setMaxAttempts] = useState(2),
    [batchGeneration, setBatchGeneration] = useState(false),
    [tokenBudget, setTokenBudget] = useState(0),
    [planningBudget, setPlanningBudget] = useState(0),
    [answerDetail, setAnswerDetail] = useState<'concise' | 'full'>('concise'),
    [style, setStyle] = useState('适度变式'),
    [duration, setDuration] = useState(60),
    [plan, setPlan] = useState<ExamPlan | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [docsLoading, setDocsLoading] = useState(false),
    [preview, setPreview] = useState<
      { name: string; document_id: string; page: number; text: string; visual?: boolean }[] | null
    >(null),
    [previewBusy, setPreviewBusy] = useState(false),
    [ocrScope, setOcrScope] = useState<{ doc: Document; start: number; end: number } | null>(null);
  useEffect(() => {
    if (!courseId && courses.data?.length) setCourseId(courses.data[0].id);
  }, [courses.data, courseId]);
  useEffect(() => {
    let current = true;
    setDocs([]);
    setRanges([]);
    setPlan(null);
    setLatest(null);
    setLocalRecovery(null);
    if (!courseId) return;
    setDocsLoading(true);
    api<ExamPlan | null>(`/courses/${courseId}/exam-plans/latest`)
      .then((data) => {
        if (current) setLatest(data);
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    api<Document[]>(`/courses/${courseId}/documents`)
      .then((data) => {
        if (current) setDocs(data);
      })
      .catch((err) => {
        if (current) setError((err as Error).message);
      })
      .finally(() => {
        if (current) setDocsLoading(false);
      });
    return () => {
      current = false;
    };
  }, [courseId]);
  const course = courses.data?.find((c) => c.id === courseId);
  const count = mode === 'custom' ? rules.reduce((n, r) => n + r.count, 0) : randomCount;
  const points = rules.reduce((n, r) => n + r.count * r.points, 0);
  const allowed = rules.filter((r) => r.count > 0);
  const selectedPages = ranges.reduce((n, r) => n + r.end - r.start + 1, 0);
  function payload(): ExamConfig {
    return {
      course_id: courseId,
      title: title.trim() || `${course?.name || '课程'} · 章节练习`,
      ranges,
      rules: mode === 'custom' ? rules : allowed,
      mode,
      reading_mode: readingMode,
      review_mode: reviewMode,
      random_count: randomCount,
      difficulty,
      focus,
      instructions,
      max_attempts: maxAttempts,
      token_budget: tokenBudget,
      planning_token_budget: planningBudget,
      batch_generation: batchGeneration,
      answer_detail: answerDetail,
      duration,
      style,
      plan_id: plan?.id,
      blueprint: plan?.blueprint,
    };
  }
  function applyConfig(c: ExamConfig) {
    setTitle(c.title);
    setRanges(c.ranges);
    setMode(c.mode);
    setReadingMode(c.reading_mode || 'study');
    setReviewMode(c.review_mode || 'full');
    setRandomCount(c.random_count);
    setRules(initialRules.map((r) => c.rules.find((s) => s.type === r.type) || { ...r, count: 0 }));
    setDifficulty(c.difficulty);
    setFocus(c.focus);
    setInstructions(c.instructions || '');
    setMaxAttempts(c.max_attempts ?? 2);
    setTokenBudget(c.token_budget ?? 0);
    setPlanningBudget(c.planning_token_budget ?? 0);
    setBatchGeneration(c.batch_generation ?? false);
    setAnswerDetail(c.answer_detail || 'concise');
    setStyle(c.style || '适度变式');
    setDuration(c.duration);
  }
  async function restore() {
    if (!latest) return;
    try {
      const data = await api<ExamPlan>(`/exam-plans/${latest.id}`);
      const stored = readLocalDraft(data.id);
      const local = stored && {
        ...stored,
        blueprint: stored.status && stored.status !== 'ready' ? data.blueprint : stored.blueprint,
      };
      applyConfig(data.config);
      setPlan(data);
      setLatest(null);
      if (
        local &&
        !data.exam_id &&
        draftSnapshot(local.config, local.blueprint) !== draftSnapshot(data.config, data.blueprint)
      )
        setLocalRecovery(local);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function updateRange(id: string, patch: Partial<SourceRange>) {
    setRanges((prev) => prev.map((r) => (r.document_id === id ? { ...r, ...patch } : r)));
  }
  const valid =
    courseId &&
    ranges.length > 0 &&
    count > 0 &&
    count <= 30 &&
    allowed.length > 0 &&
    (readingMode !== 'vision' || selectedPages <= 4);
  return (
    <>
      <Link className="back-link" to={courseId ? `/courses/${courseId}` : '/courses'}>
        <ChevronLeft size={15} />
        返回课程
      </Link>
      <PageHeading
        eyebrow="CREATE A PRACTICE"
        title="定制这一次练习"
        description="选好范围，设定目标，让题目跟上你的学习节奏。"
      />
      {ocrScope && (
        <DocumentOCR
          {...ocrScope}
          close={() => {
            setOcrScope(null);
            setError('');
            if (plan) {
              api<ExamPlan>(`/exam-plans/${plan.id}`)
                .then((data) =>
                  setPlan((current) =>
                    current?.id === data.id ? { ...data, blueprint: current.blueprint } : current,
                  ),
                )
                .catch((e) => setError(e.message));
            }
            api<Document[]>(`/courses/${courseId}/documents`)
              .then(setDocs)
              .catch((e) => setError(e.message));
          }}
        />
      )}
      {latest && !plan && (
        <Notice>
          上次规划：{latest.config.title} ·{' '}
          {latest.status === 'running' || latest.status === 'queued'
            ? '后台规划中'
            : latest.exam_id
              ? '已提交试卷'
              : '已保存草稿'}{' '}
          · {latest.updated_at}
          <div className="button-group">
            <button type="button" className="button secondary" onClick={() => void restore()}>
              继续上次规划
            </button>
            <button type="button" className="button ghost" onClick={() => setLatest(null)}>
              新建规划
            </button>
          </div>
        </Notice>
      )}
      {localRecovery && plan && (
        <Notice>
          发现本机未保存的修改（基于版本 {localRecovery.revision}，服务器版本 {plan.revision}）。
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              applyConfig(localRecovery.config);
              setPlan({ ...plan, blueprint: localRecovery.blueprint });
              setLocalRecovery(null);
            }}
          >
            恢复本机修改
          </button>
          <button
            type="button"
            className="button ghost"
            onClick={() => {
              localStorage.removeItem(localDraftKey(plan.id));
              setLocalRecovery(null);
            }}
          >
            使用已保存版本
          </button>
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {settings.data &&
        !(readingMode === 'vision' ? settings.data.has_vision_key : settings.data.has_key) && (
          <Notice>
            还没有配置 AI API Key。你可以先选择资料，<Link to="/settings">前往设置</Link>
            后再生成。
          </Notice>
        )}
      {courses.error && <Notice tone="error">{courses.error}</Notice>}
      {courses.loading ? (
        <Loading />
      ) : !courses.data?.length ? (
        <div className="panel">
          <Empty
            icon={<BookOpen size={28} />}
            title="先创建一门课程"
            text="上传教材后，就可以按章节或 PDF 页码组卷。"
            action={
              <Link to="/courses" className="button primary">
                创建课程
                <ArrowRight size={16} />
              </Link>
            }
          />
        </div>
      ) : (
        <form
          className="generator-layout"
          onSubmit={async (e) => {
            e.preventDefault();
            if (submitting.current) return;
            if (!plan || needsPlanning(plan, payload())) {
              setError('请先生成并核对考点分配表。');
              return;
            }
            submitting.current = true;
            setBusy(true);
            setError('');
            try {
              await draftRef.current?.flush();
              const exam = await api<Exam>(
                '/exams',
                json('POST', { ...payload(), submission_id: plan.id }),
              );
              navigate(`/exams/${exam.id}`);
            } catch (err) {
              setError((err as Error).message);
              if (plan) {
                try {
                  const saved = await api<ExamPlan>(`/exam-plans/${plan.id}`);
                  setPlan(saved);
                  if (saved.exam_id) {
                    navigate(`/exams/${saved.exam_id}`);
                    return;
                  }
                } catch {
                  /* preserve current draft on network failure */
                }
              }
              window.scrollTo({ top: 0, behavior: 'smooth' });
            } finally {
              submitting.current = false;
              setBusy(false);
            }
          }}
        >
          <div className="generator-main">
            <section className="panel form-section">
              <div className="form-section-title">
                <span className="step-number">01</span>
                <div>
                  <h2>选择知识范围</h2>
                  <p>聚焦一章或一组知识点，练习更有针对性。</p>
                </div>
              </div>
              <div className="form-grid">
                <label>
                  所属课程
                  <select value={courseId} onChange={(e) => setCourseId(e.target.value)}>
                    {courses.data.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  试卷名称
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    maxLength={100}
                    placeholder={`${course?.name || '课程'} · 章节练习`}
                  />
                </label>
              </div>
              <label>
                资料处理方式
                <select
                  value={readingMode}
                  onChange={(e) => {
                    const value = e.target.value as 'study' | 'vision';
                    setReadingMode(value);
                    if (value === 'vision') {
                      if (mode === 'reference') setMode('custom');
                      setBatchGeneration(false);
                    }
                  }}
                >
                  <option value="study">资料学习 · 识别并缓存，适合反复复习</option>
                  <option value="vision">看图仿题 · 直接读取原图，适合少量习题截图</option>
                </select>
              </label>
              {readingMode === 'vision' && (
                <Notice>
                  直接读取所选图片或 PDF 页面，无需先识别文字。每次最多 4
                  页；分配表在本机生成，不提取考点、不调用
                  API。出题与审题使用所选识图模型，可能多次读取原图，反复使用同一资料时不一定更省。
                </Notice>
              )}
              {readingMode === 'vision' && selectedPages > 4 && (
                <Notice tone="error">
                  当前选择 {selectedPages} 页，看图仿题最多 4 页，请缩小范围。
                </Notice>
              )}
              <label className="field-title">教材、图片与 PDF 页码范围</label>
              {docsLoading ? (
                <Loading label="正在读取教材…" />
              ) : docs.length === 0 ? (
                <div className="inline-empty">
                  这门课程还没有教材。
                  <Link to={`/courses/${courseId}`}>
                    去上传 PDF
                    <ArrowRight size={14} />
                  </Link>
                </div>
              ) : (
                docs.map((doc) => {
                  const scope = ranges.find((r) => r.document_id === doc.id);
                  return (
                    <div className={`scope-card ${scope ? 'selected' : ''}`} key={doc.id}>
                      <label className="scope-title">
                        <input
                          type="checkbox"
                          checked={!!scope}
                          onChange={(e) =>
                            setRanges(
                              e.target.checked
                                ? [
                                    ...ranges,
                                    {
                                      document_id: doc.id,
                                      start: 1,
                                      end: Math.min(doc.page_count, 10),
                                    },
                                  ]
                                : ranges.filter((r) => r.document_id !== doc.id),
                            )
                          }
                        />
                        <FileText size={18} />
                        <span>
                          {doc.name}
                          <small>
                            {doc.page_count} 页 · {doc.kind} · {doc.usable_pages ?? 0} 页有可用文字
                          </small>
                        </span>
                      </label>
                      {scope && readingMode === 'study' && (
                        <div className="ocr-scope-action">
                          <span>
                            {doc.usable_pages === 0
                              ? '扫描教材需先识别文字与公式，再生成测验。'
                              : '选中范围若为扫描页或公式提取不完整，可先识别。'}
                          </span>
                          <button
                            type="button"
                            className="button secondary"
                            onClick={() => setOcrScope({ doc, start: scope.start, end: scope.end })}
                          >
                            识别所选页
                          </button>
                        </div>
                      )}
                      {scope && (
                        <div className="scope-fields">
                          <label>
                            资料用途
                            <select
                              aria-label={`${doc.name} 资料用途`}
                              value={scope.role || 'auto'}
                              onChange={(e) =>
                                updateRange(doc.id, { role: e.target.value as SourceRange['role'] })
                              }
                            >
                              <option value="auto">按资料类型自动区分</option>
                              <option value="knowledge">知识依据（教材 / 笔记）</option>
                              <option value="reference">命题参考（往年卷 / 样题）</option>
                            </select>
                          </label>
                          <label>
                            开始页
                            <input
                              aria-label={`${doc.name} 开始页`}
                              type="number"
                              min={1}
                              max={doc.page_count}
                              value={scope.start}
                              onChange={(e) =>
                                updateRange(doc.id, { start: Number(e.target.value) })
                              }
                              required
                            />
                          </label>
                          <span>至</span>
                          <label>
                            结束页
                            <input
                              aria-label={`${doc.name} 结束页`}
                              type="number"
                              min={scope.start}
                              max={doc.page_count}
                              value={scope.end}
                              onChange={(e) => updateRange(doc.id, { end: Number(e.target.value) })}
                              required
                            />
                          </label>
                          {doc.outline.length > 0 && (
                            <label className="grow">
                              按目录选择
                              <select
                                value=""
                                onChange={(e) => {
                                  const index = Number(e.target.value),
                                    start = doc.outline[index].page;
                                  const next = doc.outline
                                    .slice(index + 1)
                                    .find(
                                      (o) => o.depth <= doc.outline[index].depth && o.page > start,
                                    );
                                  updateRange(doc.id, {
                                    start,
                                    end: next ? next.page - 1 : doc.page_count,
                                  });
                                }}
                              >
                                <option value="" disabled>
                                  选择章节
                                </option>
                                {doc.outline.map((o, i) => (
                                  <option value={i} key={i}>
                                    {o.title}
                                  </option>
                                ))}
                              </select>
                            </label>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
              <p className="field-help">
                页码按 PDF 实际页序，从 1 开始。选定范围越大，越难保证每个知识点都被覆盖。
              </p>
            </section>
            <section className="panel form-section">
              <div className="form-section-title">
                <span className="step-number">02</span>
                <div>
                  <h2>安排题型与分值</h2>
                  <p>自行搭配，或让系统在选定题型中随机分配。</p>
                </div>
              </div>
              <div className="segmented">
                <button
                  type="button"
                  className={mode === 'custom' ? 'selected' : ''}
                  onClick={() => setMode('custom')}
                >
                  <SlidersHorizontal size={16} />
                  自定义题型
                </button>
                <button
                  type="button"
                  className={mode === 'random' ? 'selected' : ''}
                  onClick={() => setMode('random')}
                >
                  <Shuffle size={16} />
                  随机搭配
                </button>
                <button
                  type="button"
                  disabled={readingMode === 'vision'}
                  className={mode === 'reference' ? 'selected' : ''}
                  onClick={() => {
                    setMode('reference');
                    setRules(rules.map((r) => ({ ...r, count: 1 })));
                  }}
                >
                  参考往年卷
                </button>
              </div>
              <div className="rule-table">
                <div className="rule-row rule-header">
                  <span>题型</span>
                  <span>{mode === 'custom' ? '题目数量' : '允许出题'}</span>
                  <span>每题分值</span>
                </div>
                {rules.map((rule, index) => (
                  <div className="rule-row" key={rule.type}>
                    <span>{typeNames[rule.type]}</span>
                    {mode === 'custom' ? (
                      <input
                        aria-label={`${typeNames[rule.type]}数量`}
                        type="number"
                        min={0}
                        max={30}
                        value={rule.count}
                        onChange={(e) =>
                          setRules(
                            rules.map((r, i) =>
                              i === index ? { ...r, count: Number(e.target.value) } : r,
                            ),
                          )
                        }
                      />
                    ) : (
                      <input
                        aria-label={`允许${typeNames[rule.type]}`}
                        type="checkbox"
                        checked={rule.count > 0}
                        onChange={(e) =>
                          setRules(
                            rules.map((r, i) =>
                              i === index ? { ...r, count: e.target.checked ? 1 : 0 } : r,
                            ),
                          )
                        }
                      />
                    )}
                    <input
                      aria-label={`${typeNames[rule.type]}分值`}
                      type="number"
                      min={0.5}
                      max={100}
                      step={0.5}
                      value={rule.points}
                      onChange={(e) =>
                        setRules(
                          rules.map((r, i) =>
                            i === index ? { ...r, points: Number(e.target.value) } : r,
                          ),
                        )
                      }
                    />
                  </div>
                ))}
              </div>
              {mode !== 'custom' && (
                <label className="random-count">
                  试卷总题量
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={randomCount}
                    onChange={(e) => setRandomCount(Number(e.target.value))}
                  />
                  <span className="field-help">
                    {mode === 'reference'
                      ? '按命题参考中提取的题型和考点比例分配，题数以本页设置为准；不保证还原原卷，生成前请查看分配表。'
                      : '各题型随机分配，可能不包含所有选中题型；总分生成后确定。'}
                  </span>
                </label>
              )}
            </section>
            <section className="panel form-section">
              <div className="form-section-title">
                <span className="step-number">03</span>
                <div>
                  <h2>设定练习目标</h2>
                  <p>从基础理解开始，再逐步挑战综合应用。</p>
                </div>
              </div>
              <div className="difficulty-options">
                {[
                  { name: '基础巩固', desc: '概念理解 · 直接应用' },
                  { name: '综合应用', desc: '知识联系 · 多步推导' },
                  { name: '挑战题', desc: '深入分析 · 证明拓展' },
                ].map((d) => (
                  <button
                    type="button"
                    key={d.name}
                    className={`difficulty-option ${difficulty === d.name ? 'selected' : ''}`}
                    onClick={() => setDifficulty(d.name)}
                  >
                    <span>
                      {d.name}
                      {difficulty === d.name && <Check size={15} />}
                    </span>
                    <small>{d.desc}</small>
                  </button>
                ))}
              </div>
              <label>
                重点知识或学习目标 <span className="muted">（可选）</span>
                <textarea
                  rows={3}
                  maxLength={500}
                  value={focus}
                  onChange={(e) => setFocus(e.target.value)}
                  placeholder="例如：重点练习条件概率与事件独立性，注意区分两者的概念。"
                />
              </label>
              <label>
                自定义命题指令（可选）
                <textarea
                  rows={3}
                  maxLength={2000}
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  placeholder="例如：模仿往年题型和考点生成一份试卷，改变数值与情境，避免直接复制原题。题型比例请同时选择“参考往年卷”。"
                />
              </label>
              <details>
                <summary>用量与答案设置</summary>
                <label>
                  <input
                    type="checkbox"
                    disabled={readingMode === 'vision'}
                    checked={batchGeneration}
                    onChange={(e) => setBatchGeneration(e.target.checked)}
                  />
                  尝试合并两道共用相同依据的题目（逐题独立审查，复杂题建议关闭）
                </label>
                <label>
                  审题策略
                  <select
                    value={reviewMode}
                    onChange={(e) => setReviewMode(e.target.value as 'full' | 'adaptive')}
                  >
                    <option value="full">完整审题（独立解题＋答案一致性核验）</option>
                    <option value="adaptive">按风险审题（简单纯文字单选、判断题合并审查）</option>
                  </select>
                </label>
                <p className="field-help">
                  合并审查会同时看到答案，不能视为独立盲审；图片、表格、多选、不定项、填空、计算和证明题仍完整审题。表格、无法辨认或未转写图形会对照原图复核，另计图片输入用量。
                </p>
                <label>
                  每题最多尝试次数（含首次）
                  <input
                    type="number"
                    min={1}
                    max={3}
                    value={maxAttempts}
                    onChange={(e) => setMaxAttempts(Number(e.target.value))}
                  />
                </label>
                <label>
                  出题累计 token 预算阈值（0 为不限）
                  <input
                    type="number"
                    min={0}
                    max={10000000}
                    step={1000}
                    value={tokenBudget}
                    onChange={(e) => setTokenBudget(Number(e.target.value))}
                  />
                </label>
                <p className="field-help">
                  累计包含生成与审题、失败请求已报告的用量；达到阈值后暂停后续调用，当前请求可能超出。规划和
                  OCR 另计。网络失败未报告的用量无法计入。
                </p>
                <label>
                  单次规划 token 预算阈值（0 为不限）
                  <input
                    type="number"
                    min={0}
                    max={10000000}
                    step={1000}
                    value={planningBudget}
                    onChange={(e) => setPlanningBudget(Number(e.target.value))}
                  />
                </label>
                <p className="field-help">
                  达到阈值后停止后续规划请求，当前请求可能超出。已完成片段保留缓存，可提高预算后重新规划。
                </p>
                <label>
                  解析详细程度
                  <select
                    value={answerDetail}
                    onChange={(e) => setAnswerDetail(e.target.value as 'concise' | 'full')}
                  >
                    <option value="concise">简洁解析（保留关键步骤）</option>
                    <option value="full">详细推导</option>
                  </select>
                </label>
              </details>
              <label>
                出题方式
                <select value={style} onChange={(e) => setStyle(e.target.value)}>
                  <option>贴近原题</option>
                  <option>适度变式</option>
                  <option>情景应用</option>
                </select>
              </label>
              <p className="field-help">
                按所选策略核对题目与答案解析，会增加 API 用量；表格或识别存疑时对照原图。AI
                审题仍可能漏错。
              </p>
              <label className="duration-field">
                建议用时（分钟）
                <input
                  type="number"
                  min={5}
                  max={240}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                />
              </label>
            </section>
            <Blueprint
              key={plan?.id || courseId}
              ref={draftRef}
              suspendSave={!!localRecovery}
              plan={plan}
              config={payload()}
              enabled={
                !!valid &&
                !!(readingMode === 'vision'
                  ? settings.data?.has_vision_key
                  : settings.data?.has_key)
              }
              changed={setPlan}
            />
          </div>
          <aside className="generation-summary">
            <div className="panel summary-panel">
              <div className="summary-icon">
                <Sparkles size={24} />
              </div>
              <h2>这次练习，准备好了</h2>
              <p>留一点时间，认真思考每一道题。</p>
              <dl>
                <div>
                  <dt>课程</dt>
                  <dd>{course?.name}</dd>
                </div>
                <div>
                  <dt>资料范围</dt>
                  <dd>
                    {ranges.length} 份 · {selectedPages} 页
                  </dd>
                </div>
                <div>
                  <dt>题目总数</dt>
                  <dd>{count} 题</dd>
                </div>
                <div>
                  <dt>试卷总分</dt>
                  <dd>
                    {mode === 'custom'
                      ? `${points} 分`
                      : mode === 'reference'
                        ? '按参考分配后确定'
                        : '随机分配后确定'}
                  </dd>
                </div>
                <div>
                  <dt>难度</dt>
                  <dd>{difficulty}</dd>
                </div>
                <div>
                  <dt>建议用时</dt>
                  <dd>{duration} 分钟</dd>
                </div>
              </dl>
              <button
                className="button primary full"
                type="submit"
                disabled={
                  busy ||
                  !valid ||
                  !(readingMode === 'vision'
                    ? settings.data?.has_vision_key
                    : settings.data?.has_key) ||
                  needsPlanning(plan, payload()) ||
                  !!plan?.exam_id ||
                  !!localRecovery
                }
              >
                <Sparkles size={17} />
                {busy ? '正在创建…' : '确认分配并生成测验'}
              </button>
              <button
                className="button ghost full"
                type="button"
                disabled={!valid || previewBusy}
                onClick={async () => {
                  setPreviewBusy(true);
                  setError('');
                  try {
                    const data = await api<{
                      sources: {
                        name: string;
                        document_id: string;
                        page: number;
                        text: string;
                        visual?: boolean;
                      }[];
                    }>('/retrieval-preview', json('POST', payload()));
                    setPreview(data.sources);
                  } catch (err) {
                    setError((err as Error).message);
                  } finally {
                    setPreviewBusy(false);
                  }
                }}
              >
                <Eye size={16} />
                {previewBusy
                  ? '正在读取…'
                  : readingMode === 'vision'
                    ? '预览所选原图'
                    : '预览检索片段'}
              </button>
              <p className="summary-note">
                生成将调用 所选 AI 服务
                API，按实际用量计费。题目逐题审查并保存，可在用量设置中开启小批量生成，通常需要等待数分钟。
              </p>
            </div>
            <div className="quiet-note">
              <BookOpen size={17} />
              <span>生成的解析是学习参考。尤其是计算与证明，请结合教材核验。</span>
            </div>
          </aside>
        </form>
      )}
      {preview && (
        <Modal title="检索片段预览" close={() => setPreview(null)}>
          <Notice>
            {readingMode === 'vision'
              ? '以下原图会用于出题与审题，未进行全文转写。'
              : '下面是一次检索示例。生成每道题时会在同一范围内选择相关片段；不会保证覆盖全部选中页面。'}
          </Notice>
          {preview.map((s, i) => (
            <div className="retrieval-snippet" key={i}>
              <strong>
                {s.name} · PDF 第 {s.page} 页
              </strong>
              {s.visual ? (
                <img
                  className="source-preview-image"
                  src={`/api/documents/${s.document_id}/pages/${s.page}/image`}
                  alt={`${s.name} 第 ${s.page} 页`}
                />
              ) : (
                <pre>{s.text}</pre>
              )}
            </div>
          ))}
        </Modal>
      )}
    </>
  );
}
