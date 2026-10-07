import type { ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import { AlertCircle, ArrowRight, LoaderCircle, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import { Link } from 'react-router-dom';

export function MathText({ children, className = '' }: { children: string; className?: string }) {
  const normalized = children
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, s: string) => `$$${s}$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, s: string) => `$${s}$`);
  const text = normalized
    .split(/(\$\$[\s\S]*?\$\$|\$[^\n$]*?\$)/g)
    .map((segment) =>
      segment.startsWith('$')
        ? segment.replace(
            /\[\[blank:(\d+)\]\]/g,
            (_, n: string) => `\\underline{\\hspace{2em}}\\text{(${n})}`,
          )
        : segment.replace(/\[\[blank:(\d+)\]\]/g, '____（$1）'),
    )
    .join('');
  return (
    <div className={`math-text ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkMath, remarkGfm]}
        rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false, trust: false }]]}
        skipHtml
        components={{ img: () => null, a: ({ children }) => <span>{children}</span> }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function Notice({
  children,
  tone = 'info',
}: {
  children: ReactNode;
  tone?: 'info' | 'error' | 'success';
}) {
  return (
    <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <AlertCircle size={17} />
      <div>{children}</div>
    </div>
  );
}

export function Loading({ label = '正在加载…' }: { label?: string }) {
  return (
    <div className="loading">
      <LoaderCircle className="spin" size={22} />
      {label}
    </div>
  );
}

export function Empty({
  icon,
  title,
  text,
  action,
}: {
  icon: ReactNode;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

export function SectionHeading({ title, link, to }: { title: string; link?: string; to?: string }) {
  return (
    <div className="section-heading">
      <h2>{title}</h2>
      {link && to && (
        <Link to={to}>
          {link}
          <ArrowRight size={15} />
        </Link>
      )}
    </div>
  );
}

export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const old = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeRef.current();
      if (event.key === 'Tab') {
        const elements = ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href]',
        );
        if (!elements?.length) return;
        const first = elements[0],
          last = elements[elements.length - 1];
        if (
          event.shiftKey &&
          (document.activeElement === first || document.activeElement === ref.current)
        ) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', handler);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = overflow;
      old?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={ref}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="关闭" onClick={close}>
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Status({ status }: { status: string }) {
  const names: Record<string, string> = {
    ready: '已完成',
    queued: '等待生成',
    generating: '生成中',
    partial: '待重试',
    paused: '已暂停',
    failed: '未完成',
    pending: '等待生成',
  };
  return <span className={`badge status-${status}`}>{names[status] || status}</span>;
}
