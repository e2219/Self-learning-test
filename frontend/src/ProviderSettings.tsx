import { useState } from 'react';
import { api, json } from './api';
import { Notice } from './ui';

export type Provider = {
  thinking?: string;
  input_price?: number | null;
  cached_price?: number | null;
  output_price?: number | null;
  enabled?: boolean;
  name?: string;
  base_url?: string;
  model?: string;
  has_key?: boolean;
  json_mode?: boolean;
  image_detail?: string;
  active_name: string;
  active_model: string;
};
export function ProviderSettings({
  role,
  value,
  reload,
}: {
  role: 'text' | 'vision';
  value: Provider;
  reload: () => Promise<unknown>;
}) {
  const [form, setForm] = useState({
    enabled: value.enabled || false,
    name: value.name || '兼容服务',
    base_url: value.base_url || '',
    model: value.model || '',
    api_key: '',
    thinking: value.thinking || 'provider_default',
    input_price: value.input_price?.toString() ?? '',
    cached_price: value.cached_price?.toString() ?? '',
    output_price: value.output_price?.toString() ?? '',
    json_mode: value.json_mode ?? true,
    image_detail: value.image_detail || 'high',
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [message, setMessage] = useState('');
  const change = (patch: Partial<typeof form>) => setForm({ ...form, ...patch });
  async function run(test: boolean) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      if (test) {
        const r = await api<{ message: string }>(`/settings/providers/${role}/test`, json('POST'));
        setMessage(r.message);
      } else {
        await api(
          `/settings/providers/${role}`,
          json('PUT', {
            ...form,
            input_price: form.input_price === '' ? null : Number(form.input_price),
            cached_price: form.cached_price === '' ? null : Number(form.cached_price),
            output_price: form.output_price === '' ? null : Number(form.output_price),
          }),
        );
        setForm({ ...form, api_key: '' });
        await reload();
        setMessage('接口已保存。');
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel form-section">
      <h2>{role === 'text' ? '出题与规划接口' : '识图与图片审题接口'}</h2>
      <p>
        当前：{value.active_name} · {value.active_model}
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      {message && <Notice tone="success">{message}</Notice>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(false);
        }}
      >
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => change({ enabled: e.target.checked })}
          />
          使用自定义 OpenAI 兼容接口（关闭后使用原 DeepSeek 设置）
        </label>
        {form.enabled && (
          <>
            <label>
              服务名称
              <input
                required
                value={form.name}
                maxLength={60}
                onChange={(e) => change({ name: e.target.value })}
              />
            </label>
            <label>
              API 基地址
              <input
                required
                type="url"
                placeholder="https://服务商域名/v1"
                value={form.base_url}
                onChange={(e) => change({ base_url: e.target.value })}
              />
            </label>
            <label>
              模型 ID
              <input
                required
                value={form.model}
                placeholder="填写服务商提供的确切模型 ID"
                onChange={(e) => change({ model: e.target.value })}
              />
            </label>
            <label>
              此接口的 API Key
              <input
                type="password"
                autoComplete="off"
                value={form.api_key}
                placeholder={value.has_key ? '已保存；同地址留空保留' : '输入该服务的密钥'}
                onChange={(e) => change({ api_key: e.target.value })}
              />
            </label>
            <p className="field-help">
              更换地址必须重新填写密钥。所选教材内容将发送到此地址；两个接口的密钥分别保存。
            </p>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={form.json_mode}
                onChange={(e) => change({ json_mode: e.target.checked })}
              />
              接口支持 JSON Object 模式（不支持时取消；仍会核验返回格式）
            </label>
            <details>
              <summary>思考参数与参考计价（可选）</summary>
              <label>
                思考模式
                <select
                  value={form.thinking}
                  onChange={(e) => change({ thinking: e.target.value })}
                >
                  <option value="provider_default">服务商默认（不发送 thinking 参数）</option>
                  <option value="enabled">开启 thinking</option>
                  <option value="disabled">关闭 thinking</option>
                </select>
              </label>
              <p className="field-help">
                仅在服务商支持 thinking.type 时选择开启或关闭；选择显式模式后，普通 OCR
                会请求关闭思考。
              </p>
              {(['input_price', 'cached_price', 'output_price'] as const).map((field, i) => (
                <label key={field}>
                  {['普通输入', '缓存命中输入', '输出'][i]}单价（美元 / 百万 tokens）
                  <input
                    type="number"
                    min={0}
                    max={10000}
                    step="any"
                    value={form[field]}
                    onChange={(e) => change({ [field]: e.target.value })}
                  />
                </label>
              ))}
              <p className="field-help">
                三项一起填写或全部留空。仅估算新请求，不回算旧记录；实际费用以服务商账单为准。
              </p>
            </details>
            {role === 'vision' && (
              <label>
                图片 detail 参数
                <select
                  value={form.image_detail}
                  onChange={(e) => change({ image_detail: e.target.value })}
                >
                  <option value="high">high</option>
                  <option value="auto">auto</option>
                  <option value="low">low</option>
                  <option value="original">original（仅服务商明确支持时选择）</option>
                </select>
              </label>
            )}
            <p className="field-help">
              支持 /chat/completions 协议；识图模型还须支持 image_url。仅填写 Key
              不能让纯文本模型获得识图能力。
            </p>
          </>
        )}
        <div className="button-group">
          <button className="button primary" disabled={busy}>
            保存{role === 'text' ? '出题' : '识图'}接口
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={() => void run(true)}
          >
            检查已保存接口
          </button>
        </div>
      </form>
    </section>
  );
}
