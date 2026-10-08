import { MaterialQuality } from './MaterialQuality';
import { useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileText,
  FolderOpen,
  Library,
  MoreHorizontal,
  NotebookPen,
  Plus,
  Save,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react';
import { DocumentOCR } from './OCR';
import { api, date, json, upload as uploadFile, useRemote } from './api';
import type { Course, Document, Exam, Page, Settings } from './types';
import { Empty, Loading, MathText, Modal, Notice, PageHeading, SectionHeading, Status } from './ui';

function CourseCard({ course, index }: { course: Course; index: number }) {
  const symbols = ['∑', 'P', '∀', '∫'];
  return (
    <Link className={`course-card color-${index % 4}`} to={`/courses/${course.id}`}>
      <div className="course-card-top">
        <div className="course-symbol">{symbols[index % 4]}</div>
        <ArrowRight size={18} />
      </div>
      <h3>{course.name}</h3>
      <p>{course.description || '从教材开始，建立你的练习与复习空间。'}</p>
      <div className="course-meta">
        <span>
          <FileText size={14} />
          {course.document_count} 份资料
        </span>
        <span>{course.exam_count} 份试卷</span>
      </div>
    </Link>
  );
}

export function Dashboard() {
  const courses = useRemote<Course[]>('/courses'),
    exams = useRemote<Exam[]>('/exams');
  const list = courses.data || [],
    papers = exams.data || [];
  const metrics = [
    { label: '学习中的课程', value: list.length, icon: BookOpen, caption: '独立资料与学习记录' },
    {
      label: '已收录的资料',
      value: list.reduce((n, c) => n + c.document_count, 0),
      icon: Library,
      caption: '让每一道题有据可循',
    },
    { label: '生成的试卷', value: papers.length, icon: FileText, caption: '每一次练习都被保留' },
    {
      label: '待巩固的错题',
      value: list.reduce((n, c) => n + c.wrong_count, 0),
      icon: NotebookPen,
      caption: '回顾薄弱点，再进一步',
    },
  ];
  return (
    <>
      <PageHeading
        eyebrow="LEARNING OVERVIEW"
        title="今天，也学得更扎实一点。"
        description="你的课程、资料与每一次进步，都在这里。"
        action={
          <Link className="button primary" to="/generate">
            <Plus size={17} />
            创建测验
          </Link>
        }
      />
      {courses.error && <Notice tone="error">{courses.error}</Notice>}
      {exams.error && <Notice tone="error">{exams.error}</Notice>}
      <section className="hero">
        <div className="hero-copy">
          <div className="hero-label">
            <span />
            从教材到掌握
          </div>
          <h2>
            把知识变成练习，
            <br />
            把思考变成<span>真正的理解。</span>
          </h2>
          <p>
            上传课程教材，定制专属测验。
            <br />
            按自己的节奏练习，让每一道题都有收获。
          </p>
          <Link className="button primary" to={list.length ? '/generate' : '/courses'}>
            {list.length ? '开始一次新练习' : '创建我的第一门课程'}
            <ArrowRight size={17} />
          </Link>
          <span className="hero-footnote">文字与公式 · 参考解析 · 试卷打印</span>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <span className="float-symbol symbol-one">∑</span>
          <span className="float-symbol symbol-two">∞</span>
          <div className="art-paper back" />
          <div className="art-paper">
            <div className="art-paper-title">
              <span className="art-mini-icon">∴</span>一次有收获的练习
            </div>
            <div className="art-line wide" />
            <div className="art-line short" />
            <div className="art-formula">
              <MathText>{'$P(A \\cap B)=P(A)P(B)$'}</MathText>
            </div>
            <div className="art-choice">
              <span />
              <div className="art-line" />
            </div>
            <div className="art-choice selected">
              <span>
                <Check size={11} />
              </span>
              <div className="art-line" />
            </div>
            <div className="art-choice">
              <span />
              <div className="art-line" />
            </div>
            <div className="art-paper-footer">理解 · 练习 · 巩固</div>
          </div>
          <div className="art-sticker">
            <Check size={17} />
            每一步，都算数
          </div>
        </div>
      </section>
      <div className="metric-grid">
        {metrics.map(({ label, value, icon: Icon, caption }) => (
          <div className="metric" key={label}>
            <div className="metric-top">
              <span>{label}</span>
              <Icon size={18} />
            </div>
            <strong>{value.toString().padStart(2, '0')}</strong>
            <small>{caption}</small>
          </div>
        ))}
      </div>
      <SectionHeading title="我的课程" link="管理全部课程" to="/courses" />
      {courses.loading ? (
        <Loading />
      ) : list.length ? (
        <div className="course-grid">
          {list.slice(0, 3).map((c, i) => (
            <CourseCard key={c.id} course={c} index={i} />
          ))}
        </div>
      ) : (
        <div className="onboarding">
          <div className="onboarding-icon">
            <BookOpen size={30} />
          </div>
          <div>
            <h3>从一门课程开始</h3>
            <p>创建课程后，上传 PDF 教材，就可以生成第一份测验。</p>
          </div>
          <Link className="button secondary" to="/courses">
            <Plus size={16} />
            添加课程
          </Link>
        </div>
      )}
      <div className="dashboard-bottom">
        <section>
          <SectionHeading title="最近的试卷" link="查看全部" to="/exams" />
          <div className="panel">
            {papers.length ? (
              papers.slice(0, 4).map((p) => (
                <Link className="exam-row" key={p.id} to={`/exams/${p.id}`}>
                  <div className="document-icon">
                    <FileText size={20} />
                  </div>
                  <div className="grow">
                    <strong>{p.title}</strong>
                    <span>
                      {p.course_name} · {date(p.created_at)} · {p.question_count} 题
                    </span>
                  </div>
                  <Status status={p.status} />
                  <ChevronRight size={17} />
                </Link>
              ))
            ) : (
              <Empty
                icon={<FileText size={26} />}
                title="第一份试卷，等待诞生"
                text="从指定章节出题，为下一次复习做好准备。"
              />
            )}
          </div>
        </section>
        <section>
          <SectionHeading title="学习小贴士" />
          <div className="tip-card">
            <div className="tip-icon">
              <CircleHelp size={23} />
            </div>
            <span className="eyebrow">LEARN WITH INTENTION</span>
            <h3>先思考，再看答案。</h3>
            <p>
              把计算与推导写在纸上，再对照参考解析自行评分。比起记住答案，理解每一步为什么成立更重要。
            </p>
            <div className="tip-footer">
              <span>01 / 学习方法</span>
              <span>✦</span>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

export function Courses() {
  const { data, error, loading, reload } = useRemote<Course[]>('/courses');
  const [show, setShow] = useState(false),
    [name, setName] = useState(''),
    [description, setDescription] = useState(''),
    [busy, setBusy] = useState(false),
    [formError, setFormError] = useState('');
  const navigate = useNavigate();
  return (
    <>
      <PageHeading
        eyebrow="MY COURSES"
        title="我的课程"
        description="每一门课程，都有自己的知识与练习空间。"
        action={
          <button className="button primary" onClick={() => setShow(true)}>
            <Plus size={17} />
            添加课程
          </button>
        }
      />
      {error && <Notice tone="error">{error}</Notice>}
      {loading ? (
        <Loading />
      ) : data?.length ? (
        <div className="course-grid">
          {data.map((c, i) => (
            <CourseCard key={c.id} course={c} index={i} />
          ))}
        </div>
      ) : (
        <div className="panel">
          <Empty
            icon={<BookOpen size={32} />}
            title="开始构建你的课程库"
            text="例如离散数学、概率论。每门课程的教材与试卷将分别保存。"
            action={
              <button className="button primary" onClick={() => setShow(true)}>
                <Plus size={17} />
                创建课程
              </button>
            }
          />
        </div>
      )}
      {show && (
        <Modal title="创建一门课程" close={() => setShow(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setFormError('');
              try {
                const course = await api<Course>('/courses', json('POST', { name, description }));
                await reload();
                navigate(`/courses/${course.id}`);
              } catch (err) {
                setFormError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              课程名称
              <input
                placeholder="例如：离散数学"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={80}
              />
            </label>
            <label>
              课程说明 <span className="muted">（可选）</span>
              <textarea
                placeholder="例如：本学期课程，重点复习集合、关系与图论"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={500}
                rows={3}
              />
            </label>
            {formError && <Notice tone="error">{formError}</Notice>}
            <div className="modal-actions">
              <button type="button" className="button secondary" onClick={() => setShow(false)}>
                取消
              </button>
              <button className="button primary" type="submit" disabled={busy}>
                {busy ? '创建中…' : '创建课程'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

function DocumentPreview({ doc, close }: { doc: Document; close: () => void }) {
  const [number, setNumber] = useState(1),
    [text, setText] = useState(''),
    [editing, setEditing] = useState(false),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false);
  const page = useRemote<Page>(`/documents/${doc.id}/pages/${number}`);
  const changePage = (value: number) => {
    if (editing && !window.confirm('切换页面会放弃未保存的修正，继续吗？')) return;
    setEditing(false);
    setMessage('');
    setNumber(value);
  };
  return (
    <Modal title={doc.name} close={close}>
      <div className="preview-toolbar">
        <div className="pager">
          <button
            className="icon-button"
            disabled={number <= 1}
            onClick={() => changePage(number - 1)}
            aria-label="上一页"
          >
            <ChevronLeft size={18} />
          </button>
          <label className="inline-label">
            PDF 页码
            <input
              type="number"
              min={1}
              max={doc.page_count}
              value={number}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (n >= 1 && n <= doc.page_count) changePage(n);
              }}
            />
          </label>
          <span>/ {doc.page_count}</span>
          <button
            className="icon-button"
            disabled={number >= doc.page_count}
            onClick={() => changePage(number + 1)}
            aria-label="下一页"
          >
            <ChevronRight size={18} />
          </button>
        </div>
        <a
          className="text-link"
          href={`/api/documents/${doc.id}/file#page=${number}`}
          target="_blank"
          rel="noreferrer"
        >
          查看原 PDF <ArrowDownToLine size={14} />
        </a>
      </div>
      {doc.outline.length > 0 && (
        <label>
          跳转目录
          <select value="" onChange={(e) => changePage(Number(e.target.value))}>
            <option value="" disabled>
              选择章节（来自 PDF 书签）
            </option>
            {doc.outline.map((o, i) => (
              <option key={i} value={o.page}>
                {'　'.repeat(Math.min(o.depth, 3))}
                {o.title} · 第 {o.page} 页
              </option>
            ))}
          </select>
        </label>
      )}
      {page.error && <Notice tone="error">{page.error}</Notice>}
      {page.loading ? (
        <Loading />
      ) : (
        <>
          {page.data?.warning && <Notice>{page.data.warning}</Notice>}
          {page.data && !editing && (
            <MaterialQuality
              key={`${doc.id}-${number}`}
              docId={doc.id}
              page={page.data}
              reload={page.reload}
            />
          )}
          <div className="section-heading">
            <h3>解析文本 {page.data?.edited ? <span className="badge">已修正</span> : null}</h3>
            {!editing && (
              <button
                className="text-link"
                onClick={() => {
                  setText(page.data?.text || '');
                  setEditing(true);
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
                aria-label="页面解析文本"
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={14}
              />
              <p className="field-help">
                支持手动补充 LaTeX，例如 $P(A)=0.5$。修正仅影响解析文本，原 PDF 保留。
              </p>
              <button
                className="button primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api(`/documents/${doc.id}/pages/${number}`, json('PUT', { text }));
                    await page.reload();
                    setEditing(false);
                    setMessage('页面修正已保存。');
                  } catch (err) {
                    setMessage((err as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Save size={15} />
                保存修正
              </button>
            </>
          ) : (
            <div className="page-text">
              <MathText>
                {page.data?.text ||
                  '此页未提取到文字。请关闭预览，在资料卡片点击「文字与公式识别」，也可手动补充。'}
              </MathText>
            </div>
          )}
        </>
      )}
      {message && <Notice>{message}</Notice>}
    </Modal>
  );
}

export function CoursePage() {
  const { courseId } = useParams(),
    navigate = useNavigate();
  const courses = useRemote<Course[]>('/courses'),
    docs = useRemote<Document[]>(`/courses/${courseId}/documents`),
    exams = useRemote<Exam[]>(`/exams?course_id=${courseId}`),
    settings = useRemote<Settings>('/settings');
  const course = courses.data?.find((c) => c.id === courseId);
  const [uploading, setUploading] = useState(false),
    [uploadProgress, setUploadProgress] = useState(0),
    [message, setMessage] = useState(''),
    [kind, setKind] = useState('教材'),
    [preview, setPreview] = useState<Document | null>(null),
    [ocrDoc, setOcrDoc] = useState<Document | null>(null),
    [manage, setManage] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const maxBytes = settings.data?.max_pdf_bytes ?? 1024 * 1024 * 1024;
  const maxPages = settings.data?.max_pdf_pages ?? 2000;
  const sizeLimit = `${maxBytes / (1024 * 1024)} MB`;
  async function upload(file: File) {
    const image = /\.(png|jpe?g|webp)$/i.test(file.name);
    if (file.size > (image ? 20 * 1024 * 1024 : maxBytes)) {
      setMessage(image ? '单张图片不能超过 20 MB。' : `PDF 不能超过 ${sizeLimit}。`);
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    setMessage('');
    const body = new FormData();
    body.append('file', file);
    body.append('kind', kind);
    try {
      await uploadFile(`/courses/${courseId}/documents`, body, setUploadProgress);
      await docs.reload();
      await courses.reload();
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }
  return (
    <>
      <Link className="back-link" to="/courses">
        <ChevronLeft size={15} />
        全部课程
      </Link>
      <PageHeading
        eyebrow="COURSE LIBRARY"
        title={course?.name || '课程资料'}
        description={course?.description || '整理教材、检查解析，然后开启一次有依据的练习。'}
        action={
          <div className="button-group">
            <button
              className="icon-button"
              aria-label="管理课程"
              onClick={() => setManage(!manage)}
            >
              <MoreHorizontal size={21} />
            </button>
            <Link className="button primary" to={`/generate?course=${courseId}`}>
              <Sparkles size={17} />
              生成测验
            </Link>
          </div>
        }
      />
      {manage && (
        <div className="panel manage-panel">
          <span>删除课程将同时删除教材、试卷和学习记录。</span>
          <button
            className="button danger"
            onClick={async () => {
              if (
                !window.confirm(`确认删除「${course?.name}」及其全部资料和记录？此操作不可撤销。`)
              )
                return;
              try {
                await api(`/courses/${courseId}`, json('DELETE'));
                navigate('/courses');
              } catch (err) {
                setMessage((err as Error).message);
              }
            }}
          >
            <Trash2 size={15} />
            删除课程
          </button>
        </div>
      )}
      {(message || docs.error || courses.error) && (
        <Notice tone="error">{message || docs.error || courses.error}</Notice>
      )}
      <div className="course-layout">
        <section>
          <SectionHeading title={`课程资料 · ${docs.data?.length || 0}`} />
          <div
            className="upload-zone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (!uploading && e.dataTransfer.files[0]) void upload(e.dataTransfer.files[0]);
            }}
          >
            <div className="upload-icon">
              <Upload size={24} />
            </div>
            <h3>
              {uploading
                ? uploadProgress < 100
                  ? `正在上传教材 · ${uploadProgress}%`
                  : '正在保存并解析教材…'
                : '把教材放进你的学习空间'}
            </h3>
            <p>
              支持 PDF、JPG、PNG、WebP。PDF 最多 {sizeLimit} / {maxPages} 页；静态图片最多 20 MB /
              4000 万像素，作为单页资料导入后识别。
            </p>
            {uploading && (
              <div role="status">
                <progress
                  className="upload-progress"
                  aria-label="教材上传进度"
                  value={uploadProgress}
                  max={100}
                />
                <p>
                  {uploadProgress < 100
                    ? '正在传输文件，请保持页面打开。'
                    : '文件已发送，正在处理内容。大型教材可能需要数分钟，请保持页面打开。'}
                </p>
              </div>
            )}
            <div className="upload-controls">
              <select
                aria-label="资料类型"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                disabled={uploading}
              >
                {['教材', '习题集', '往年试卷', '个人笔记'].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
              <button
                className="button primary"
                disabled={uploading}
                onClick={() => fileRef.current?.click()}
              >
                <Plus size={16} />
                {uploading ? '处理中…' : '选择 PDF 或图片'}
              </button>
              <input
                hidden
                ref={fileRef}
                type="file"
                accept="application/pdf,.pdf,image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
                onChange={(e) => {
                  if (e.target.files?.[0]) void upload(e.target.files[0]);
                }}
              />
            </div>
          </div>
          {docs.loading ? (
            <Loading />
          ) : (
            <div className="document-list">
              {docs.data?.map((doc) => (
                <div className="document-card" key={doc.id}>
                  <div className="document-main">
                    <div className="document-icon">
                      <FileText size={23} />
                    </div>
                    <div className="grow">
                      <h3>{doc.name}</h3>
                      <p>
                        {doc.kind} · {doc.page_count} 页 ·{' '}
                        {doc.outline.length ? '已提取书签目录' : '按 PDF 页码选择范围'}
                      </p>
                    </div>
                    <button
                      className="icon-button muted"
                      aria-label={`删除 ${doc.name}`}
                      onClick={async () => {
                        if (!window.confirm('确认删除这份资料？')) return;
                        try {
                          await api(`/documents/${doc.id}`, json('DELETE'));
                          await docs.reload();
                        } catch (err) {
                          setMessage((err as Error).message);
                        }
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                  <div className="document-card-bottom">
                    <span>
                      {doc.usable_pages
                        ? `${doc.usable_pages}/${doc.page_count} 页有可用文字`
                        : '未提取到正文，请先识别扫描页'}
                    </span>
                    <button className="text-link" onClick={() => setOcrDoc(doc)}>
                      文字与公式识别
                    </button>
                    <button className="text-link" onClick={() => setPreview(doc)}>
                      预览与修正
                      <ArrowRight size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
        <aside className="course-aside">
          <div className="panel reading-note">
            <span className="eyebrow">BEFORE YOU GENERATE</span>
            <h3>资料准备小指南</h3>
            <ol>
              <li>
                <strong>优先使用文字型 PDF</strong>
                <p>扫描教材可使用「文字与公式识别」，再对照原页核验。</p>
              </li>
              <li>
                <strong>检查公式与页码</strong>
                <p>出题范围使用 PDF 实际页序，可能与书上印刷页码不同。</p>
              </li>
              <li>
                <strong>小范围，更有针对性</strong>
                <p>先选择一个章节，确认题目质量后逐步扩大范围。</p>
              </li>
            </ol>
          </div>
          <SectionHeading title="这门课的试卷" />
          {exams.data?.length ? (
            <div className="panel">
              {exams.data.slice(0, 5).map((e) => (
                <Link className="mini-exam" key={e.id} to={`/exams/${e.id}`}>
                  <FileText size={17} />
                  <span>{e.title}</span>
                  <ChevronRight size={15} />
                </Link>
              ))}
            </div>
          ) : (
            <div className="panel">
              <Empty
                icon={<FolderOpen size={25} />}
                title="还没有试卷"
                text="上传教材后，就可以创建第一份测验。"
              />
            </div>
          )}
        </aside>
      </div>
      {ocrDoc && (
        <DocumentOCR
          doc={ocrDoc}
          close={() => {
            setOcrDoc(null);
            void docs.reload();
          }}
        />
      )}
      {preview && <DocumentPreview doc={preview} close={() => setPreview(null)} />}
    </>
  );
}
