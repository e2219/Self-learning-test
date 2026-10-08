import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { BookOpen, Share2 } from 'lucide-react';
import { api as localApi, json } from './api';
import type { Course, Exam } from './types';
import { MathText, Notice } from './ui';
import { newSubmissionId } from './draft';
import { typeNames } from './types';
import type { QuestionType } from './types';
import 'katex/dist/katex.min.css';
import './styles.css';
import './library.css';

const roleNames: Record<string, string> = {
  owner: '创建者',
  admin: '管理员',
  member: '普通成员',
  removed: '已移除',
};

type User = { id: string; username: string; nickname: string };
type Library = {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  role: 'owner' | 'admin' | 'member';
  post_count?: number;
  members?: { id: string; nickname: string; role: string }[];
};
type Pack = {
  format: string;
  version: number;
  kind: 'exam' | 'mistakes';
  title: string;
  course: string;
  questions: {
    type: QuestionType;
    stem: string;
    points: number;
    options: string[];
    answer: string;
    explanation: string;
    knowledge: string;
    rubric: string[];
  }[];
};
type Post = {
  id: string;
  title: string;
  course: string;
  kind: string;
  author: string;
  author_id: string;
  revision: number;
  view_revision: number;
  updated_at: string;
  favorite: boolean;
  note: string;
  pack: Pack;
  history: { revision: number; note: string; created_at: string }[];
};

export function LibraryApp({ embedded = false }: { embedded?: boolean }) {
  const api = <T,>(path: string, options: RequestInit = {}) =>
    localApi<T>(embedded ? '/library/remote' + path : path, options);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [server, setServer] = useState(''),
    [connected, setConnected] = useState(!embedded);
  const [exams, setExams] = useState<Exam[]>([]),
    [courses, setCourses] = useState<Course[]>([]);
  const [selectedExam, setSelectedExam] = useState(params.get('share') || '');
  const [targetCourse, setTargetCourse] = useState('');
  const [copies, setCopies] = useState<{ id: string; revision: number }[]>([]);
  const [importId, setImportId] = useState(newSubmissionId);
  const [joinLibraryId, setJoinLibraryId] = useState(params.get('library') || '');
  const [joinPassword, setJoinPassword] = useState(''),
    [accessPassword, setAccessPassword] = useState('');
  const [newAccessPassword, setNewAccessPassword] = useState('');
  const [createdPassword, setCreatedPassword] = useState('');
  const [activeServer, setActiveServer] = useState('');
  const Content = embedded ? 'section' : 'main';
  async function refreshLocal() {
    const [archive, classes] = await Promise.all([
      localApi<Exam[]>('/exams'),
      localApi<Course[]>('/courses'),
    ]);
    setExams(archive);
    setCourses(classes);
  }
  async function loadSelectedExam() {
    if (!selectedExam) throw new Error('请先选择历史试卷。');
    const data = await localApi<Pack>(`/exams/${selectedExam}/share`);
    setPack(data);
    setNote('');
    setUploadId(newSubmissionId());
  }
  async function importPost(newCopy = false) {
    if (!post) return;
    const result = await localApi<{ id: string }>(
      '/library/imports',
      json('POST', {
        post_id: post.id,
        revision: post.view_revision,
        course_id: targetCourse,
        new_copy: newCopy,
        submission_id: importId,
      }),
    );
    navigate(`/exams/${result.id}`);
  }
  const [user, setUser] = useState<User | null>(null),
    [loaded, setLoaded] = useState(false);
  const [register, setRegister] = useState(false),
    [username, setUsername] = useState(''),
    [password, setPassword] = useState(''),
    [nickname, setNickname] = useState(''),
    [registrationCode, setRegistrationCode] = useState('');
  const [libraries, setLibraries] = useState<Library[]>([]),
    [library, setLibrary] = useState<Library | null>(null),
    [posts, setPosts] = useState<Post[]>([]),
    [post, setPost] = useState<Post | null>(null);
  const [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [invite, setInvite] = useState('');
  const [name, setName] = useState(''),
    [description, setDescription] = useState(''),
    [joinCode, setJoinCode] = useState('');
  const [search, setSearch] = useState(''),
    [kind, setKind] = useState(''),
    [favorites, setFavorites] = useState(false),
    [offset, setOffset] = useState(0);
  const [pack, setPack] = useState<Pack | null>(null),
    [note, setNote] = useState(''),
    [revising, setRevising] = useState(false),
    [uploadId, setUploadId] = useState(newSubmissionId);
  const locked = useRef(false);
  const previewRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (pack) previewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [pack]);
  async function act(work: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError('');
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function resumeLink() {
    const id = params.get('library'),
      postId = params.get('post');
    if (id && postId) {
      if (embedded && params.get('server')) {
        const current = await localApi<{ server: string }>('/library/connection');
        if (current.server !== params.get('server'))
          throw new Error(`请先连接来源服务器：${params.get('server')}`);
      }
      await openLibrary(id);
      await openPost(postId);
    }
  }
  async function home() {
    setLibraries(await api('/libraries'));
    setLibrary(null);
    setPost(null);
    setPack(null);
    setInvite('');
    setCreatedPassword('');
    window.scrollTo(0, 0);
  }
  async function list(id: string, start = 0) {
    setPosts(
      await api(
        `/libraries/${id}/posts?search=${encodeURIComponent(search)}&kind=${kind}&favorites=${favorites}&offset=${start}`,
      ),
    );
    setOffset(start);
  }
  async function openLibrary(id: string) {
    const data = await api<Library>(`/libraries/${id}`);
    setLibrary(data);
    setPost(null);
    setPack(null);
    setRevising(false);
    if (embedded) await refreshLocal();
    await list(id);
    window.scrollTo(0, 0);
  }
  async function openPost(id: string, revision?: number) {
    setPost(await api(`/posts/${id}${revision ? `?revision=${revision}` : ''}`));
    setCopies([]);
    setImportId(newSubmissionId());
    if (embedded) {
      await refreshLocal();
      const status = await localApi<{ copies: { id: string; revision: number }[] }>(
        `/library/import-status/${id}`,
      );
      setCopies(status.copies);
    }
    setPack(null);
    setRevising(false);
    window.scrollTo(0, 0);
  }
  useEffect(() => {
    async function initialize() {
      if (embedded) {
        const config = await localApi<{ server: string; connected: boolean }>(
          '/library/connection',
        );
        setServer(config.server === 'local' ? '' : config.server);
        setActiveServer(config.server);
        setConnected(config.connected);
        if (!config.connected) return;
      }
      try {
        setUser(await api<User>('/me'));
        setLibraries(await api('/libraries'));
        await resumeLink();
      } catch (e) {
        if (embedded && (e as Error).message !== '请先登录共享学习库。')
          setError((e as Error).message);
      }
    }
    initialize()
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoaded(true));
  }, []);
  const owner = !!user && library?.owner_id === user.id;
  const canManage = owner || library?.role === 'admin';
  return (
    <div className={`library-shell ${embedded ? 'library-embedded' : ''}`}>
      <header className="library-header">
        <a href={embedded ? '/library' : '/'} className="brand">
          <BookOpen />
          <strong>知习 · 共享学习库</strong>
        </a>
        {user && (
          <div className="button-group">
            <span>{user.nickname}</span>
            <button
              className="button ghost small"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api('/logout', json('POST'));
                  setUser(null);
                  setLibrary(null);
                  setPost(null);
                  setPack(null);
                  setInvite('');
                })
              }
            >
              {embedded ? '退出共享账号' : '退出登录'}
            </button>
          </div>
        )}
      </header>
      <Content className="library-content">
        {embedded && (
          <>
            <Notice>
              {activeServer === 'local'
                ? '本机学习库已就绪，无需填写服务器地址或额外启动服务。资料保存在这台电脑上。'
                : '当前使用远程学习库。远程服务不可用时，可切换到本机学习库；已有远程资料会保留。'}
              {activeServer !== 'local' && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await localApi('/library/connection', json('PUT', { server: 'local' }));
                      setActiveServer('local');
                      setConnected(true);
                      setUser(null);
                      setLibrary(null);
                      setPost(null);
                      setPack(null);
                      setInvite('');
                      setCreatedPassword('');
                      try {
                        setUser(await api<User>('/me'));
                        await home();
                      } catch {
                        /* Sign in to the local account. */
                      }
                    })
                  }
                >
                  使用本机学习库
                </button>
              )}
            </Notice>
            <details className="panel">
              <summary>连接远程学习库（可选）</summary>
              <p>
                输入部署后的共享学习库网址。本机测试可填
                http://127.0.0.1:8001；手机也通过电脑后台连接。
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void act(async () => {
                    const config = await localApi<{ server: string }>(
                      '/library/connection',
                      json('PUT', { server }),
                    );
                    setActiveServer(config.server);
                    setServer(config.server === 'local' ? '' : config.server);
                    setConnected(true);
                    setUser(null);
                    setLibrary(null);
                    setPost(null);
                    setPack(null);
                    setInvite('');
                    setCreatedPassword('');
                    try {
                      setUser(await api<User>('/me'));
                      await home();
                    } catch {
                      /* New connection requires its own account. */
                    }
                  });
                }}
              >
                <label>
                  共享服务器地址
                  <input
                    type="url"
                    required
                    value={server}
                    onChange={(e) => setServer(e.target.value)}
                    placeholder="https://study.example.com"
                  />
                </label>
                <button className="button secondary" disabled={busy}>
                  连接服务器
                </button>
              </form>
            </details>
          </>
        )}
        {error && <Notice tone="error">{error}</Notice>}
        {!loaded ? (
          <p>正在读取学习库…</p>
        ) : !connected ? (
          <p>连接共享服务器后，即可登录、分享和加入学习库。</p>
        ) : !user ? (
          <section className="panel library-auth">
            <span className="eyebrow">STUDY TOGETHER</span>
            <h1>{register ? '创建个人账号' : '欢迎回到学习库'}</h1>
            <p>
              {embedded && activeServer === 'local'
                ? '注册或登录本机学习库账号。数据保存在当前电脑，不同电脑的本机库不会自动同步。'
                : '用当前服务的共享账号登录，再通过库编号和入库密码加入同学的学习库。'}
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void act(async () => {
                  if (register)
                    await api(
                      '/register',
                      json('POST', {
                        username: username.trim(),
                        password,
                        nickname,
                        registration_code: registrationCode,
                      }),
                    );
                  setUser(
                    await api('/login', json('POST', { username: username.trim(), password })),
                  );
                  setPassword('');
                  await home();
                  await resumeLink();
                });
              }}
            >
              <label>
                用户名
                <input
                  required
                  aria-label="用户名"
                  pattern="[a-zA-Z0-9_]{3,32}"
                  maxLength={32}
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
                <small>3–32 位英文字母、数字或下划线</small>
              </label>
              {register && (
                <label>
                  昵称
                  <input
                    required
                    maxLength={40}
                    value={nickname}
                    onChange={(e) => setNickname(e.target.value)}
                  />
                </label>
              )}
              <label>
                密码
                <input
                  required
                  type="password"
                  minLength={10}
                  maxLength={128}
                  aria-label="密码"
                  autoComplete={register ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <small>至少 10 位字符</small>
              </label>
              {register && (
                <label>
                  站点注册口令（如管理员要求）
                  <input
                    type="password"
                    maxLength={200}
                    value={registrationCode}
                    onChange={(e) => setRegistrationCode(e.target.value)}
                  />
                </label>
              )}
              <button className="button primary" disabled={busy}>
                {busy ? '请稍候…' : register ? '注册并登录' : '登录'}
              </button>
            </form>
            <button
              className="text-link"
              onClick={() => {
                setRegister(!register);
                setError('');
              }}
            >
              {register ? '已有账号，去登录' : '还没有账号，去注册'}
            </button>
          </section>
        ) : (
          <>
            <nav className="library-nav">
              <button className="text-link" disabled={busy} onClick={() => void act(home)}>
                我的学习库
              </button>
              {library && (
                <>
                  <span> / </span>
                  <button
                    className="text-link"
                    disabled={busy}
                    onClick={() => void act(() => openLibrary(library.id))}
                  >
                    {library.name}
                  </button>
                </>
              )}
            </nav>
            {invite && !post && (
              <Notice>
                <strong>学习库邀请码：</strong>
                <code className="invite-code">{invite}</code>
                <p>
                  请复制保存并发给同学。仅显示这一次；创建者和管理员可以更换邀请码，旧码随即失效。
                </p>
              </Notice>
            )}
            {!library ? (
              <>
                <h1>一起积累，分别练习。</h1>
                <p>
                  {embedded
                    ? '选择历史试卷分享，或将同学的试卷直接加入自己的历史试卷。'
                    : '分享试卷和错题，查看后下载试卷包，在自己的知习项目中导入练习。'}
                </p>
                <div className="library-grid">
                  <form
                    className="panel"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void act(async () => {
                        const created = await api<{
                          id: string;
                          invite_code: string;
                          access_password: string;
                        }>(
                          '/libraries',
                          json('POST', { name, description, access_password: accessPassword }),
                        );
                        setInvite(created.invite_code);
                        setCreatedPassword(created.access_password);
                        setAccessPassword('');
                        setName('');
                        setDescription('');
                        await openLibrary(created.id);
                      });
                    }}
                  >
                    <h2>创建学习库</h2>
                    <label>
                      学习库名称
                      <input
                        required
                        maxLength={80}
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="例如：概率论期末复习"
                      />
                    </label>
                    <label>
                      简介
                      <textarea
                        maxLength={500}
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                      />
                    </label>
                    <label>
                      入库密码（留空自动生成）
                      <input
                        type="password"
                        minLength={8}
                        maxLength={128}
                        value={accessPassword}
                        onChange={(e) => setAccessPassword(e.target.value)}
                        autoComplete="new-password"
                      />
                    </label>
                    <button className="button primary" disabled={busy}>
                      创建学习库
                    </button>
                  </form>
                  <form
                    className="panel"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void act(async () => {
                        const joined = await api<{ id: string }>(
                          '/libraries/join',
                          json(
                            'POST',
                            joinLibraryId
                              ? {
                                  library_id: joinLibraryId.includes('://')
                                    ? new URL(joinLibraryId).searchParams.get('library') || ''
                                    : joinLibraryId.trim(),
                                  password: joinPassword,
                                }
                              : { invite_code: joinCode.trim() },
                          ),
                        );
                        setJoinCode('');
                        setJoinPassword('');
                        setJoinLibraryId('');
                        setInvite('');
                        await openLibrary(joined.id);
                      });
                    }}
                  >
                    <h2>加入同学的学习库</h2>
                    <label>
                      库编号或邀请链接
                      <input
                        value={joinLibraryId}
                        onChange={(e) => setJoinLibraryId(e.target.value)}
                        maxLength={500}
                      />
                    </label>
                    <label>
                      入库密码
                      <input
                        type="password"
                        value={joinPassword}
                        onChange={(e) => setJoinPassword(e.target.value)}
                        required={!!joinLibraryId}
                        maxLength={128}
                      />
                    </label>
                    <label>
                      学习库邀请码
                      <input
                        required={!joinLibraryId}
                        minLength={8}
                        maxLength={100}
                        value={joinCode}
                        onChange={(e) => setJoinCode(e.target.value)}
                      />
                    </label>
                    <button className="button secondary" disabled={busy}>
                      加入学习库
                    </button>
                  </form>
                </div>
                <h2>我的学习库</h2>
                <div className="library-grid">
                  {[...libraries]
                    .sort((a, b) => Number(b.role === 'owner') - Number(a.role === 'owner'))
                    .map((lib) => (
                      <button
                        className="panel library-card"
                        key={lib.id}
                        disabled={busy}
                        onClick={() =>
                          void act(async () => {
                            setInvite('');
                            await openLibrary(lib.id);
                          })
                        }
                      >
                        <h3>{lib.name}</h3>
                        <p>{lib.description || '共同整理课程练习'}</p>
                        <span>
                          {lib.post_count} 份内容 · {roleNames[lib.role]} ·{' '}
                          {lib.role === 'owner' ? '我创建的库' : '我加入的库'}
                        </span>
                      </button>
                    ))}
                </div>
                {!libraries.length && <p>还没有加入学习库，可以创建一个或输入同学发来的邀请码。</p>}
                <details className="panel">
                  <summary>修改账号密码</summary>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const values = new FormData(e.currentTarget);
                      void act(async () => {
                        await api(
                          '/password',
                          json('PUT', {
                            old_password: values.get('old'),
                            new_password: values.get('new'),
                          }),
                        );
                        setUser(null);
                        setPassword('');
                      });
                    }}
                  >
                    <label>
                      原密码
                      <input name="old" type="password" required autoComplete="current-password" />
                    </label>
                    <label>
                      新密码
                      <input
                        name="new"
                        type="password"
                        required
                        minLength={10}
                        maxLength={128}
                        autoComplete="new-password"
                      />
                    </label>
                    <button className="button secondary" disabled={busy}>
                      修改并重新登录
                    </button>
                  </form>
                </details>
              </>
            ) : (
              <>
                <h1>{post ? post.pack.title : library.name}</h1>
                <p>
                  {post
                    ? `${post.author} · ${post.pack.course} · 版本 ${post.view_revision}`
                    : `${library.description} · 我的角色：${roleNames[library.role]}`}
                </p>
                <p className="field-help">
                  库编号：<code>{library.id}</code>
                </p>
                {createdPassword && !post && (
                  <Notice>
                    入库密码：<code>{createdPassword}</code>
                    （仅本次显示，请保存后与库编号一起发给同学）
                  </Notice>
                )}
                {!post ? (
                  <>
                    <section className="panel">
                      <h2>上传试卷或错题</h2>
                      <p>
                        在个人项目的试卷页点击“导出试卷包”，或在错题页导出练习包，然后选择 JSON
                        文件。仅发布题目、参考答案与解析，不包含个人评分或原教材。
                      </p>
                      {embedded && (
                        <div className="panel">
                          <label>
                            选择历史试卷
                            <select
                              aria-label="选择历史试卷"
                              value={selectedExam}
                              onChange={(e) => setSelectedExam(e.target.value)}
                            >
                              <option value="">请选择</option>
                              {exams
                                .filter((e) => (e.ready_count ?? 0) > 0)
                                .map((e) => (
                                  <option key={e.id} value={e.id}>
                                    {e.title} · {e.course_name}（{e.ready_count}/{e.question_count}{' '}
                                    题）
                                  </option>
                                ))}
                            </select>
                          </label>
                          <button
                            className="button secondary"
                            disabled={busy || !selectedExam}
                            onClick={() => void act(loadSelectedExam)}
                          >
                            从历史试卷添加
                          </button>
                          <p className="field-help">
                            仅分享已完成题目；个人作答、成绩、API Key 和教材不会上传。
                          </p>
                        </div>
                      )}
                      <label>
                        选择试卷包
                        <input
                          type="file"
                          accept=".json,application/json"
                          disabled={busy}
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            e.target.value = '';
                            if (!file) return;
                            void act(async () => {
                              setPack(null);
                              if (file.size > 2 * 1024 * 1024)
                                throw new Error('试卷包不能超过 2 MB。');
                              const data = JSON.parse(await file.text());
                              if (
                                data.format !== 'zhixi-study-pack' ||
                                data.version !== 1 ||
                                !Array.isArray(data.questions) ||
                                !data.questions.length
                              )
                                throw new Error('请选择知习导出的试卷包。');
                              setPack(await api<Pack>('/packs/preview', json('POST', data)));
                              setNote('');
                              setUploadId(newSubmissionId());
                            });
                          }}
                        />
                      </label>
                    </section>
                    <form
                      className="library-filters"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void act(() => list(library.id));
                      }}
                    >
                      <input
                        aria-label="搜索库内内容"
                        placeholder="搜索标题、课程、发布者或发布说明"
                        maxLength={100}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                      <select
                        aria-label="内容类型"
                        value={kind}
                        onChange={(e) => setKind(e.target.value)}
                      >
                        <option value="">全部内容</option>
                        <option value="exam">试卷</option>
                        <option value="mistakes">错题与练习</option>
                      </select>
                      <label className="library-checkbox">
                        <input
                          type="checkbox"
                          checked={favorites}
                          onChange={(e) => setFavorites(e.target.checked)}
                        />
                        只看我的收藏
                      </label>
                      <button className="button secondary" disabled={busy}>
                        查询
                      </button>
                    </form>
                    <div className="library-grid">
                      {posts.map((item) => (
                        <button
                          className="panel library-card"
                          key={item.id}
                          disabled={busy}
                          onClick={() => void act(() => openPost(item.id))}
                        >
                          <span className="badge">
                            {item.kind === 'exam' ? '试卷' : '错题与练习'}
                          </span>
                          <h2>{item.title}</h2>
                          <p>
                            {item.course} · {item.author}
                          </p>
                          <p>{item.note}</p>
                          <small>
                            版本 {item.revision} {item.favorite ? ' · 已收藏' : ''}
                          </small>
                        </button>
                      ))}
                    </div>
                    {!posts.length && <p>还没有符合条件的内容，试试上传第一份试卷。</p>}
                    <div className="button-group">
                      <button
                        className="button ghost"
                        disabled={busy || offset === 0}
                        onClick={() => void act(() => list(library.id, offset - 50))}
                      >
                        上一页
                      </button>
                      <span>第 {Math.floor(offset / 50) + 1} 页</span>
                      <button
                        className="button ghost"
                        disabled={busy || posts.length < 50}
                        onClick={() => void act(() => list(library.id, offset + 50))}
                      >
                        下一页
                      </button>
                    </div>
                    <details className="panel" key="members">
                      <summary>成员与邀请码</summary>
                      {embedded && activeServer === 'local' ? (
                        <p>
                          此库保存在本机。库编号和密码不会自动使它在其他电脑上可见；互联网共享请使用远程学习库。
                        </p>
                      ) : (
                        <label>
                          邀请链接
                          <input
                            aria-label="邀请链接"
                            readOnly
                            value={`${embedded ? activeServer : window.location.origin}/?library=${library.id}`}
                            onFocus={(e) => e.target.select()}
                          />
                        </label>
                      )}
                      {(!embedded || activeServer !== 'local') && (
                        <p className="field-help">
                          将邀请链接与入库密码分别发给同学，链接不包含密码。
                        </p>
                      )}
                      {canManage && (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            if (
                              window.confirm(
                                '重设入库密码后，旧密码及旧邀请码失效，已加入成员保留。继续吗？',
                              )
                            )
                              void act(async () => {
                                await api(
                                  `/libraries/${library.id}/access-password`,
                                  json('PUT', { password: newAccessPassword }),
                                );
                                setNewAccessPassword('');
                                setInvite('');
                                setCreatedPassword('');
                                window.alert('入库密码已重设。');
                              });
                          }}
                        >
                          <label>
                            新入库密码
                            <input
                              type="password"
                              required
                              minLength={8}
                              maxLength={128}
                              value={newAccessPassword}
                              onChange={(e) => setNewAccessPassword(e.target.value)}
                            />
                          </label>
                          <button className="button secondary" disabled={busy}>
                            重设入库密码
                          </button>
                        </form>
                      )}
                      {canManage && (
                        <button
                          className="button secondary"
                          disabled={busy}
                          onClick={() => {
                            if (window.confirm('更换后旧邀请码失效，已加入成员不受影响。继续吗？'))
                              void act(async () =>
                                setInvite(
                                  (
                                    await api<{ invite_code: string }>(
                                      `/libraries/${library.id}/invite`,
                                      json('POST'),
                                    )
                                  ).invite_code,
                                ),
                              );
                          }}
                        >
                          更换邀请码
                        </button>
                      )}
                      <p className="field-help">
                        所有成员均可查看、下载和上传。创建者任免管理员；管理员可删除发布、移除或恢复普通成员。
                      </p>
                      {library.members
                        ?.filter((member) => canManage || member.role !== 'removed')
                        .map((member) => (
                          <div className="library-member" key={member.id}>
                            <span>
                              {member.nickname} · {roleNames[member.role]}
                            </span>
                            <div className="button-group">
                              {owner && ['member', 'admin'].includes(member.role) && (
                                <button
                                  className="text-link"
                                  disabled={busy}
                                  onClick={() => {
                                    const role = member.role === 'admin' ? 'member' : 'admin';
                                    if (
                                      window.confirm(
                                        role === 'admin'
                                          ? `将 ${member.nickname} 设为管理员？管理员可以删除试卷、管理普通成员和更换邀请码。`
                                          : `取消 ${member.nickname} 的管理员权限？`,
                                      )
                                    )
                                      void act(async () => {
                                        await api(
                                          `/libraries/${library.id}/members/${member.id}?role=${role}`,
                                          json('PUT'),
                                        );
                                        await openLibrary(library.id);
                                      });
                                  }}
                                >
                                  {member.role === 'admin' ? '取消管理员' : '设为管理员'}
                                </button>
                              )}
                              {canManage &&
                                member.role !== 'owner' &&
                                (owner || member.role !== 'admin') && (
                                  <button
                                    className="text-link"
                                    disabled={busy}
                                    onClick={() => {
                                      if (
                                        window.confirm(
                                          member.role === 'removed'
                                            ? '恢复该成员为普通成员？'
                                            : '移除后此成员无法查看或上传库内内容。继续吗？',
                                        )
                                      )
                                        void act(async () => {
                                          await api(
                                            `/libraries/${library.id}/members/${member.id}?role=${member.role === 'removed' ? 'member' : 'removed'}`,
                                            json('PUT'),
                                          );
                                          await openLibrary(library.id);
                                        });
                                    }}
                                  >
                                    {member.role === 'removed' ? '恢复成员' : '移除成员'}
                                  </button>
                                )}
                            </div>
                          </div>
                        ))}
                    </details>
                  </>
                ) : (
                  <>
                    {embedded && (
                      <section className="panel">
                        <h2>加入我的历史试卷</h2>
                        <label>
                          导入到课程
                          <select
                            aria-label="导入到课程"
                            value={targetCourse}
                            onChange={(e) => setTargetCourse(e.target.value)}
                          >
                            <option value="">按试卷课程自动匹配或新建</option>
                            {courses.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        {copies.some((c) => c.revision === post.view_revision) ? (
                          <>
                            <p>此版本已导入，不会重复创建。</p>
                            <Link
                              className="button primary"
                              to={`/exams/${copies.find((c) => c.revision === post.view_revision)!.id}`}
                            >
                              打开已有副本
                            </Link>
                            <button
                              className="button secondary"
                              disabled={busy}
                              onClick={() => void act(() => importPost(true))}
                            >
                              再创建一份
                            </button>
                          </>
                        ) : (
                          <>
                            {copies.length > 0 && (
                              <Notice>你已导入其他版本。本次会创建独立副本，保留旧版作答。</Notice>
                            )}
                            <button
                              className="button primary"
                              disabled={busy}
                              onClick={() => void act(() => importPost())}
                            >
                              加入我的历史试卷
                            </button>
                          </>
                        )}
                      </section>
                    )}
                    <div className="button-group">
                      <a
                        className="button primary"
                        href={`/api${embedded ? '/library/remote' : ''}/posts/${post.id}/download?revision=${post.view_revision}`}
                      >
                        <Share2 size={17} />
                        下载试卷包
                      </a>
                      <button
                        className="button secondary"
                        disabled={busy}
                        onClick={() =>
                          void act(async () => {
                            await api(
                              `/posts/${post.id}/favorite?enabled=${!post.favorite}`,
                              json('PUT'),
                            );
                            await openPost(post.id, post.view_revision);
                          })
                        }
                      >
                        {post.favorite ? '取消收藏' : '收藏内容'}
                      </button>
                      {(post.author_id === user.id || canManage) && (
                        <button
                          className="button ghost"
                          disabled={busy}
                          onClick={() => {
                            if (
                              window.confirm('删除这份发布及所有修订记录？已经下载的副本不受影响。')
                            )
                              void act(async () => {
                                await api(`/posts/${post.id}`, json('DELETE'));
                                await openLibrary(library.id);
                              });
                          }}
                        >
                          删除发布
                        </button>
                      )}
                    </div>
                    <p>
                      {embedded
                        ? '导入后即可在历史试卷中练习。此处浏览不会改动个人作答与评分。'
                        : '下载后在个人项目的“历史试卷 → 导入试卷包”中开始练习。此处浏览不会改动任何人的作答与评分。'}
                    </p>
                    <p>{post.note}</p>
                    <details className="panel" key="versions">
                      <summary>修订记录（{post.history.length} 个版本）</summary>
                      {post.history.map((v) => (
                        <p key={v.revision}>
                          <button
                            className="text-link"
                            disabled={busy}
                            onClick={() => void act(() => openPost(post.id, v.revision))}
                          >
                            查看版本 {v.revision}
                          </button>{' '}
                          · {v.created_at} · {v.note}
                        </p>
                      ))}
                    </details>
                    {post.author_id === user.id && (
                      <details className="panel">
                        <summary>上传修订版本</summary>
                        <p>
                          重新选择修订后的试卷包，旧版本仍保留。当前最新版本为 {post.revision}。
                        </p>
                        {embedded && (
                          <div>
                            <label>
                              选择修订后的历史试卷
                              <select
                                aria-label="选择修订后的历史试卷"
                                value={selectedExam}
                                onChange={(e) => setSelectedExam(e.target.value)}
                              >
                                <option value="">请选择</option>
                                {exams
                                  .filter((e) => (e.ready_count ?? 0) > 0)
                                  .map((e) => (
                                    <option key={e.id} value={e.id}>
                                      {e.title}
                                    </option>
                                  ))}
                              </select>
                            </label>
                            <button
                              className="button secondary"
                              disabled={busy || !selectedExam}
                              onClick={() =>
                                void act(async () => {
                                  await loadSelectedExam();
                                  setRevising(true);
                                })
                              }
                            >
                              从历史试卷发布修订
                            </button>
                          </div>
                        )}
                        <label>
                          修订试卷包
                          <input
                            type="file"
                            accept=".json,application/json"
                            disabled={busy}
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              e.target.value = '';
                              if (!file) return;
                              void act(async () => {
                                setPack(null);
                                if (file.size > 2 * 1024 * 1024)
                                  throw new Error('试卷包不能超过 2 MB。');
                                const data = JSON.parse(await file.text());
                                if (
                                  data.format !== 'zhixi-study-pack' ||
                                  !Array.isArray(data.questions)
                                )
                                  throw new Error('请选择知习导出的试卷包。');
                                setPack(await api<Pack>('/packs/preview', json('POST', data)));
                                setRevising(true);
                                setNote('');
                              });
                            }}
                          />
                        </label>
                      </details>
                    )}
                    <PackPreview pack={post.pack} />
                  </>
                )}
                {pack && (
                  <section className="panel library-upload-preview" ref={previewRef}>
                    <h2>发布前预览</h2>
                    <p>
                      {pack.title} · {pack.course} · {pack.questions.length} 题
                    </p>
                    <label>
                      发布说明／章节考点
                      <input
                        maxLength={1000}
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="例如：第三章，条件概率；已人工核对答案"
                      />
                    </label>
                    <Notice>
                      确认预览中的题目与参考答案可分享。试卷包不包含原教材或个人作答；题目仍需人工核对。
                    </Notice>
                    <div className="button-group">
                      <button
                        className="button primary"
                        disabled={busy}
                        onClick={() =>
                          void act(async () => {
                            const created = await api<{ id: string }>(
                              revising && post
                                ? `/posts/${post.id}`
                                : `/libraries/${library.id}/posts`,
                              json(
                                revising ? 'PUT' : 'POST',
                                revising && post
                                  ? { pack, note, revision: post.revision }
                                  : { pack, note, submission_id: uploadId },
                              ),
                            );
                            setPack(null);
                            await openPost(created.id);
                          })
                        }
                      >
                        {revising ? '确认发布修订' : '确认发布到学习库'}
                      </button>
                      <button
                        className="button ghost"
                        disabled={busy}
                        onClick={() => setPack(null)}
                      >
                        取消上传
                      </button>
                    </div>
                    <PackPreview pack={pack} />
                  </section>
                )}
              </>
            )}
          </>
        )}
      </Content>
      <footer className="library-footer">知习 · 共享题目，保留各自的学习记录</footer>
    </div>
  );
}

function PackPreview({ pack }: { pack: Pack }) {
  return (
    <div>
      {pack.questions.map((q, i) => (
        <article className="question-card" key={i}>
          <div className="question-label">
            <span className="question-number">{String(i + 1).padStart(2, '0')}</span>
            <span className="badge">{typeNames[q.type] || '题目'}</span>
            <span>{q.points} 分</span>
          </div>
          <MathText className="question-stem">{String(q.stem || '')}</MathText>
          {Array.isArray(q.options) &&
            q.options.map((option, n) => (
              <div className="option" key={n}>
                <span>{'ABCD'[n]}</span>
                <MathText>{String(option)}</MathText>
              </div>
            ))}
          <MathText className="field-help">{String(q.knowledge || '')}</MathText>
          <details className="solution">
            <summary>查看参考答案与解析</summary>
            <MathText>{String(q.answer || '')}</MathText>
            <MathText>{String(q.explanation || '')}</MathText>
            {q.rubric.length > 0 && (
              <>
                <strong>评分要点</strong>
                <ul>
                  {q.rubric.map((item, index) => (
                    <li key={index}>
                      <MathText>{item}</MathText>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </details>
        </article>
      ))}
    </div>
  );
}
