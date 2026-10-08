import { useEffect, useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import {
  ArrowRight,
  BookOpen,
  Check,
  FileText,
  GraduationCap,
  House,
  KeyRound,
  LogOut,
  NotebookPen,
  Plus,
  Settings2,
  ShieldCheck,
  Sparkles,
  Wifi,
} from 'lucide-react';
import { api, json } from './api';
import { Loading, Notice } from './ui';
import { Courses, Dashboard, CoursePage } from './Courses';
import { Generator } from './Generator';
import { ExamPage, Exams, PrintPage, Review } from './Exams';
import { WebResources } from './WebResources';
import { SettingsPage } from './Settings';

function Login({ onLogin }: { onLogin: () => void }) {
  const [code, setCode] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  return (
    <div className="login-page">
      <div className="login-story">
        <div className="brand">
          <div className="brand-icon">
            <BookOpen size={25} />
          </div>
          <span>
            知习<span className="brand-en">STUDY WITH PURPOSE</span>
          </span>
        </div>
        <div className="login-story-content">
          <span className="eyebrow">你的个人 AI 学习空间</span>
          <h1>
            从理解一个概念，
            <br />
            到掌握一门课程。
          </h1>
          <p>
            带上你的教材，把知识变成练习。
            <br />
            每一次思考，都让理解更进一步。
          </p>
          <div className="login-formula">P(A ∩ B) = P(A) · P(B)</div>
          <div className="story-features">
            <span>
              <Check size={16} />
              教材依据
            </span>
            <span>
              <Check size={16} />
              公式排版
            </span>
            <span>
              <Check size={16} />
              自主复习
            </span>
          </div>
        </div>
        <span className="login-footer">一点一滴，学有所获。</span>
      </div>
      <div className="login-panel">
        <div className="login-card">
          <div className="eyebrow">WELCOME BACK</div>
          <h2>进入学习空间</h2>
          <p>输入电脑启动时显示的访问口令。</p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError('');
              try {
                await api('/login', json('POST', { code }));
                onLogin();
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              访问口令
              <div className="input-icon">
                <KeyRound size={18} />
                <input
                  type="password"
                  value={code}
                  autoComplete="current-password"
                  autoFocus
                  required
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="输入你的访问口令"
                />
              </div>
            </label>
            {error && <Notice tone="error">{error}</Notice>}
            <button className="button primary full" disabled={busy} type="submit">
              {busy ? '正在验证…' : '开始学习'}
              <ArrowRight size={17} />
            </button>
          </form>
          <div className="login-tip">
            <Wifi size={18} />
            <span>
              手机与电脑连接同一 Wi-Fi 即可访问。
              <br />
              资料与学习记录保存在你的电脑上。
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

const nav = [
  { to: '/', label: '学习概览', icon: House },
  { to: '/courses', label: '我的课程', icon: BookOpen },
  { to: '/exams', label: '历史试卷', icon: FileText },
  { to: '/review', label: '错题与收藏', icon: NotebookPen },
  { to: '/resources', label: '资源检索', icon: BookOpen },
  { to: '/settings', label: '应用设置', icon: Settings2 },
];

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [connectionError, setConnectionError] = useState('');
  const location = useLocation();
  useEffect(() => {
    api('/session')
      .then(() => setAuthenticated(true))
      .catch((err) => {
        setAuthenticated(false);
        if ((err as Error).message.includes('fetch'))
          setConnectionError('无法连接本机服务，请确认电脑上的应用正在运行。');
      });
    const expired = () => setAuthenticated(false);
    window.addEventListener('session-expired', expired);
    return () => window.removeEventListener('session-expired', expired);
  }, []);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  if (authenticated === null) return <Loading label="正在连接你的学习空间…" />;
  if (!authenticated)
    return (
      <>
        {connectionError && <Notice tone="error">{connectionError}</Notice>}
        <Login
          onLogin={() => {
            setAuthenticated(true);
            setConnectionError('');
          }}
        />
      </>
    );
  const print = location.pathname.endsWith('/print');
  const section =
    nav.find((n) => n.to !== '/' && location.pathname.startsWith(n.to))?.label ||
    (location.pathname === '/generate' ? '创建测验' : '学习概览');
  return (
    <div className={`app ${print ? 'print-mode' : ''}`}>
      <aside className="sidebar">
        <Link to="/" className="brand">
          <div className="brand-icon">
            <BookOpen size={25} />
          </div>
          <span>
            知习<span className="brand-en">AI 学习助手</span>
          </span>
        </Link>
        <div className="workspace-label">PERSONAL WORKSPACE</div>
        <nav>
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
            >
              <Icon size={20} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Sparkles size={19} />
            <strong>让每次练习都有依据</strong>
            <p>
              从教材出发，循序渐进地
              <br />
              构建你的知识体系。
            </p>
          </div>
          <div className="local-status">
            <span className="status-dot" />
            本地学习空间
            <ShieldCheck size={15} />
          </div>
        </div>
      </aside>
      <div className="app-body">
        <header className="topbar">
          <div className="breadcrumb">
            我的工作台<span>/</span>
            <strong>{section}</strong>
          </div>
          <div className="topbar-actions">
            <span className="local-pill">
              <Wifi size={14} />
              局域网访问
            </span>
            <button
              className="icon-button"
              title="退出登录"
              aria-label="退出登录"
              onClick={async () => {
                try {
                  await api('/logout', json('POST'));
                  setAuthenticated(false);
                } catch (err) {
                  setConnectionError((err as Error).message);
                }
              }}
            >
              <LogOut size={18} />
            </button>
            <div className="avatar">
              <GraduationCap size={20} />
            </div>
          </div>
        </header>
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/resources" element={<WebResources />} />
            <Route path="/courses" element={<Courses />} />
            <Route path="/courses/:courseId" element={<CoursePage />} />
            <Route path="/generate" element={<Generator />} />
            <Route path="/exams" element={<Exams />} />
            <Route path="/exams/:examId" element={<ExamPage />} />
            <Route path="/exams/:examId/print" element={<PrintPage />} />
            <Route path="/review" element={<Review />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route
              path="*"
              element={
                <div className="empty">
                  <h1>没有找到这个页面</h1>
                  <Link className="button primary" to="/">
                    返回学习概览
                  </Link>
                </div>
              }
            />
          </Routes>
        </main>
        <footer className="app-footer">
          <span>知习 · 每一次练习，都是向前一步</span>
          <Link to="/generate">
            <Plus size={13} />
            创建测验
          </Link>
        </footer>
      </div>
    </div>
  );
}
