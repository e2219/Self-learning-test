import { useEffect, useState } from 'react';
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
  const courses = useRemote<Course[]>('/courses'),
    settings = useRemote<Settings>('/settings');
  const [courseId, setCourseId] = useState(params.get('course') || ''),
    [docs, setDocs] = useState<Document[]>([]),
    [ranges, setRanges] = useState<SourceRange[]>([]);
  const [title, setTitle] = useState(''),
    [mode, setMode] = useState('custom'),
    [rules, setRules] = useState(initialRules),
    [randomCount, setRandomCount] = useState(10),
    [difficulty, setDifficulty] = useState('基础巩固'),
    [focus, setFocus] = useState(''),
    [duration, setDuration] = useState(60),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [docsLoading, setDocsLoading] = useState(false),
    [preview, setPreview] = useState<{ name: string; page: number; text: string }[] | null>(null),
    [previewBusy, setPreviewBusy] = useState(false),
    [ocrScope, setOcrScope] = useState<{ doc: Document; start: number; end: number } | null>(null);
  useEffect(() => {
    if (!courseId && courses.data?.length) setCourseId(courses.data[0].id);
  }, [courses.data, courseId]);
  useEffect(() => {
    let current = true;
    setDocs([]);
    setRanges([]);
    if (!courseId) return;
    setDocsLoading(true);
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
      random_count: randomCount,
      difficulty,
      focus,
      duration,
    };
  }
  function updateRange(id: string, patch: Partial<SourceRange>) {
    setRanges((prev) => prev.map((r) => (r.document_id === id ? { ...r, ...patch } : r)));
  }
  const valid = courseId && ranges.length > 0 && count > 0 && count <= 30 && allowed.length > 0;
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
            api<Document[]>(`/courses/${courseId}/documents`)
              .then(setDocs)
              .catch((e) => setError(e.message));
          }}
        />
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {settings.data && !settings.data.has_key && (
        <Notice>
          还没有配置 DeepSeek API Key。你可以先选择资料，<Link to="/settings">前往设置</Link>
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
            setBusy(true);
            setError('');
            try {
              const exam = await api<Exam>('/exams', json('POST', payload()));
              navigate(`/exams/${exam.id}`);
            } catch (err) {
              setError((err as Error).message);
              window.scrollTo({ top: 0, behavior: 'smooth' });
            } finally {
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
              <label className="field-title">教材与 PDF 页码范围</label>
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
                      {scope && (
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
              {mode === 'random' && (
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
                    各题型随机分配，可能不包含所有选中题型；总分生成后确定。
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
                  <dd>{mode === 'custom' ? `${points} 分` : '随机分配后确定'}</dd>
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
                disabled={busy || !valid || !settings.data?.has_key}
              >
                <Sparkles size={17} />
                {busy ? '正在创建…' : '生成专属测验'}
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
                      sources: { name: string; page: number; text: string }[];
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
                {previewBusy ? '正在读取…' : '预览检索片段'}
              </button>
              <p className="summary-note">
                生成将调用 DeepSeek API，按实际用量计费。每道题单独生成并保存，通常需要等待数分钟。
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
            下面是一次检索示例。生成每道题时会在同一范围内选择相关片段；不会保证覆盖全部选中页面。
          </Notice>
          {preview.map((s, i) => (
            <div className="retrieval-snippet" key={i}>
              <strong>
                {s.name} · PDF 第 {s.page} 页
              </strong>
              <pre>{s.text}</pre>
            </div>
          ))}
        </Modal>
      )}
    </>
  );
}
