import { UsageBreakdown } from './Usage';
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { draftSnapshot, localDraftKey, needsPlanning, newSubmissionId } from './draft';
import { api, json } from './api';
import type { ExamConfig, ExamPlan } from './types';
import { typeNames } from './types';
import { Loading, Notice } from './ui';

export type DraftHandle = { flush: () => Promise<void> };
export const Blueprint = forwardRef<
  DraftHandle,
  {
    config: ExamConfig;
    enabled: boolean;
    suspendSave?: boolean;
    plan: ExamPlan | null;
    changed: (plan: ExamPlan | null) => void;
  }
>(function Blueprint({ config, enabled, plan, changed, suspendSave }, ref) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [saveState, setSaveState] = useState(''),
    [history, setHistory] = useState<
      | {
          plan_id: string;
          revision: number;
          created_at: string;
          config: ExamConfig;
          blueprint: ExamPlan['blueprint'];
        }[]
      | null
    >(null);
  const live = useRef({ config, plan, changed });
  live.current = { config, plan, changed };
  const mounted = useRef(true),
    chain = useRef(Promise.resolve());
  const requestId = useRef<string | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const running = plan?.status === 'queued' || plan?.status === 'running';
  useEffect(() => {
    if (!running || !plan) return;
    let current = true;
    const timer = setInterval(async () => {
      try {
        const data = await api<ExamPlan>(`/exam-plans/${plan.id}`);
        if (current) {
          changed(data);
          setError('');
        }
      } catch (e) {
        if (current) setError((e as Error).message);
      }
    }, 2000);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [plan?.id, running]);
  function persist() {
    const next = chain.current
      .catch(() => {})
      .then(async () => {
        const snapshot = live.current;
        if (!snapshot.plan || snapshot.plan.exam_id || snapshot.plan.status !== 'ready') return;
        setSaveState('保存中…');
        try {
          const saved = await api<ExamPlan>(
            `/exam-plans/${snapshot.plan.id}/draft`,
            json('PUT', {
              revision: snapshot.plan.revision,
              config: snapshot.config,
              blueprint: snapshot.plan.blueprint,
            }),
          );
          if (!mounted.current) return;
          const current = live.current;
          if (current.plan?.id !== saved.id) return;
          const merged = { ...saved, blueprint: current.plan.blueprint };
          live.current = { ...current, plan: merged };
          current.changed(merged);
          if (
            JSON.stringify(current.config) === JSON.stringify(snapshot.config) &&
            JSON.stringify(current.plan.blueprint) === JSON.stringify(snapshot.plan.blueprint)
          ) {
            try {
              localStorage.removeItem(localDraftKey(saved.id));
            } catch {
              /* Server save succeeded. */
            }
            setSaveState('已保存');
          }
        } catch (e) {
          if (mounted.current) {
            setSaveState('未保存到服务器，本机修改已保留');
            setError((e as Error).message);
          }
          throw e;
        }
      });
    chain.current = next;
    return next;
  }
  useImperativeHandle(ref, () => ({ flush: persist }));
  const signature = JSON.stringify([config, plan?.blueprint]);
  useEffect(() => {
    if (!plan || plan.exam_id || suspendSave) return;
    if (
      draftSnapshot(config, plan.blueprint) === draftSnapshot(plan.config, plan.blueprint) &&
      running
    )
      return;
    try {
      localStorage.setItem(
        localDraftKey(plan.id),
        JSON.stringify({
          config,
          blueprint: plan.blueprint,
          revision: plan.revision,
          status: plan.status,
        }),
      );
    } catch {
      setError('浏览器无法保存本机草稿，请保持页面打开并确认服务器保存成功。');
    }
    if (plan.status !== 'ready') return;
    setSaveState('等待保存…');
    const timer = setTimeout(() => {
      void persist().catch(() => {});
    }, 600);
    return () => clearTimeout(timer);
  }, [signature, plan?.id, plan?.status, suspendSave]);
  function update(next: ExamPlan) {
    changed(next);
  }
  return (
    <section className="panel form-section">
      <div className="form-section-title">
        <span className="step-number">04</span>
        <div>
          <h2>核对考点分配表</h2>
          <p>
            先规划整卷，逐题调整后再生成。草稿自动保存；刷新后可继续。修改设置后可复用考点缓存更新分配。
          </p>
        </div>
      </div>
      <button
        type="button"
        className="button secondary"
        disabled={!enabled || busy || running}
        onClick={async () => {
          setBusy(true);
          setError('');
          try {
            await persist();
            if (!requestId.current) requestId.current = newSubmissionId();
            const data = await api<ExamPlan>(
              '/exam-plans',
              json('POST', {
                ...config,
                parent_plan_id: plan?.id,
                submission_id: requestId.current,
              }),
            );
            requestId.current = null;
            changed(data);
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? '正在创建规划…' : plan ? '重新生成分配表' : '生成考点分配表'}
      </button>
      <p className="field-help">
        规划会调用 API
        并单独记录用量。优先参考你指定的重点、学习目标和课后习题；相同资料复用考点缓存；改变题量、分值或重点时不必重新读取未变化的内容。
      </p>
      {running && (
        <>
          <Loading label="正在阅读资料并规划考点…" />
          <button
            type="button"
            className="button ghost"
            onClick={async () => {
              try {
                const data = await api<ExamPlan>(`/exam-plans/${plan!.id}/cancel`, json('POST'));
                changed(data);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            停止后续规划
          </button>
          <p className="field-help">停止在当前调用结束后生效。关闭页面不会停止后台任务。</p>
        </>
      )}
      {plan?.status === 'cancelled' && (
        <Notice>规划已停止；当前调用仍可能产生用量，可稍后重新规划。</Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {plan && (
        <>
          <p className="field-help">
            本次规划累计 {plan.tokens} tokens · 复用 {plan.cache_hits} 个资料片段 · {saveState}
          </p>
          <UsageBreakdown rows={plan.usage} />
          {plan.exam_id && (
            <Notice>
              这份规划已经提交。<Link to={`/exams/${plan.exam_id}`}>查看已生成试卷</Link>
            </Notice>
          )}
          {plan.source_changes.map((c) => (
            <Notice key={c.key}>
              依据已变化：{c.label}。旧草稿和修改记录仍保留，请核对资料后更新规划。
            </Notice>
          ))}
          {!plan.source_changes.length &&
            needsPlanning(plan, config) &&
            plan.status === 'ready' && (
              <Notice>出题设置已变化，请更新分配表；未变化资料会复用缓存。</Notice>
            )}
          <button
            type="button"
            className="text-link"
            onClick={async () => {
              try {
                await persist();
                setHistory(await api(`/exam-plans/${plan.id}/history`));
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            查看草稿修改记录
          </button>
          {history && (
            <details open>
              <summary>已保存的历史版本</summary>
              {history.map((h, i) => (
                <div className="retrieval-snippet" key={i}>
                  <strong>
                    版本 {h.revision} · {h.created_at || '原始规划'}
                  </strong>
                  <p>
                    {h.config.title} · {h.blueprint.length} 题
                  </p>
                  {h.blueprint.map((s, j) => (
                    <p key={j}>
                      第 {j + 1} 题：{s.objective}
                    </p>
                  ))}
                </div>
              ))}
            </details>
          )}
        </>
      )}
      {plan?.error && <Notice tone="error">{plan.error}</Notice>}
      {plan?.excluded.map((p, i) => (
        <Notice key={i}>
          {p.name} · 第 {p.page} 页：{p.reason}，本次未参与规划和出题。
        </Notice>
      ))}
      {plan?.status === 'ready' && (
        <>
          {plan.blueprint.map((slot, i) => (
            <div className="scope-card" key={i}>
              <strong>
                第 {i + 1} 题 · {typeNames[slot.type]} · {slot.points} 分
              </strong>
              <label>
                考点
                <select
                  aria-label={`第 ${i + 1} 题考点`}
                  disabled={!!plan.exam_id}
                  value={slot.topic_id}
                  onChange={(e) => {
                    const topic = plan.topics.find((t) => t.id === e.target.value)!;
                    update({
                      ...plan,
                      blueprint: plan.blueprint.map((s, j) =>
                        i === j ? { ...s, topic_id: topic.id, objective: topic.objective } : s,
                      ),
                    });
                  }}
                >
                  {plan.topics.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
                </select>
              </label>
              {config.mode === 'reference' && (
                <label>
                  题型
                  <select
                    aria-label={`第 ${i + 1} 题题型`}
                    value={slot.type}
                    disabled={!!plan.exam_id}
                    onChange={(e) => {
                      const rule = config.rules.find((r) => r.type === e.target.value)!;
                      update({
                        ...plan,
                        blueprint: plan.blueprint.map((s, j) =>
                          i === j ? { ...s, type: rule.type, points: rule.points } : s,
                        ),
                      });
                    }}
                  >
                    {config.rules
                      .filter((r) => r.count > 0)
                      .map((r) => (
                        <option key={r.type} value={r.type}>
                          {typeNames[r.type]}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              <label>
                设问目标
                <input
                  aria-label={`第 ${i + 1} 题设问目标`}
                  required
                  maxLength={500}
                  disabled={!!plan.exam_id}
                  value={slot.objective}
                  onChange={(e) =>
                    update({
                      ...plan,
                      blueprint: plan.blueprint.map((s, j) =>
                        i === j ? { ...s, objective: e.target.value } : s,
                      ),
                    })
                  }
                />
              </label>
            </div>
          ))}
          <details>
            <summary>全部候选考点、来源与未覆盖项</summary>
            {plan.topics.map((t) => {
              const count = plan.blueprint.filter((s) => s.topic_id === t.id).length;
              return (
                <div className="retrieval-snippet" key={t.id}>
                  <strong>
                    {t.title} · {count ? `已分配 ${count} 题` : '尚未覆盖'}
                  </strong>
                  <p>{t.reasons.join(' · ')}</p>
                  {t.sources.map((s, i) => (
                    <p key={i}>
                      {s.name} · PDF 第 {s.page} 页：{s.quote}
                    </p>
                  ))}
                </div>
              );
            })}
          </details>
        </>
      )}
    </section>
  );
});
