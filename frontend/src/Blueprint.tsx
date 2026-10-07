import { useEffect, useState } from 'react';
import { api, json } from './api';
import type { ExamConfig, ExamPlan } from './types';
import { typeNames } from './types';
import { Loading, Notice } from './ui';

export function Blueprint({
  config,
  enabled,
  changed,
}: {
  config: ExamConfig;
  enabled: boolean;
  changed: (plan: ExamPlan | null) => void;
}) {
  const [plan, setPlan] = useState<ExamPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const running = plan?.status === 'queued' || plan?.status === 'running';
  useEffect(() => {
    if (!running || !plan) return;
    let current = true;
    const timer = setInterval(async () => {
      try {
        const data = await api<ExamPlan>(`/exam-plans/${plan.id}`);
        if (current) {
          setPlan(data);
          changed(data.status === 'ready' ? data : null);
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
  function update(next: ExamPlan) {
    setPlan(next);
    changed(next);
  }
  return (
    <section className="panel form-section">
      <div className="form-section-title">
        <span className="step-number">04</span>
        <div>
          <h2>核对考点分配表</h2>
          <p>先规划整卷，逐题调整后再生成。修改范围、题型或目标后需重新规划。</p>
        </div>
      </div>
      <button
        type="button"
        className="button secondary"
        disabled={!enabled || busy || running}
        onClick={async () => {
          setBusy(true);
          setError('');
          changed(null);
          try {
            const data = await api<ExamPlan>('/exam-plans', json('POST', config));
            setPlan(data);
            changed(data.status === 'ready' ? data : null);
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
        并单独记录用量。优先参考你指定的重点、学习目标和课后习题；每批提取主要主题，不代表涵盖所有细节。
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
                setPlan(data);
                changed(null);
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
      {plan && <p className="field-help">本次规划累计 {plan.tokens} tokens</p>}
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
              <label>
                设问目标
                <input
                  aria-label={`第 ${i + 1} 题设问目标`}
                  required
                  maxLength={500}
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
}
