import { ProviderSettings } from './ProviderSettings';
import { UsageLedger } from './Usage';
import { Backup } from './Backup';
import { useState } from 'react';
import { Check, KeyRound, Save, Server, ShieldCheck, Wifi } from 'lucide-react';
import { api, json, useRemote } from './api';
import type { Settings } from './types';
import { Loading, Notice, PageHeading } from './ui';

export function SettingsPage() {
  const settings = useRemote<Settings>('/settings');
  const [key, setKey] = useState(''),
    [model, setModel] = useState(''),
    [visionThinking, setVisionThinking] = useState(''),
    [busy, setBusy] = useState(false),
    [checking, setChecking] = useState(false),
    [message, setMessage] = useState(''),
    [error, setError] = useState('');
  return (
    <>
      <PageHeading
        eyebrow="PREFERENCES"
        title="应用设置"
        description="连接 AI，准备好属于你的学习环境。"
      />
      {settings.loading ? (
        <Loading />
      ) : (
        <div className="settings-layout">
          <div>
            <Backup />
            <UsageLedger />
            {settings.data?.providers &&
              (['text', 'vision'] as const).map((role) => (
                <ProviderSettings
                  key={role}
                  role={role}
                  value={settings.data!.providers[role]}
                  reload={settings.reload}
                />
              ))}
            <section className="panel form-section">
              <div className="form-section-title">
                <div className="settings-icon">
                  <KeyRound size={22} />
                </div>
                <div>
                  <h2>内置 DeepSeek API</h2>
                  <p>用于识别扫描页、生成题目、参考答案和逐步解析。</p>
                </div>
              </div>
              {(error || settings.error) && <Notice tone="error">{error || settings.error}</Notice>}
              {message && <Notice tone="success">{message}</Notice>}
              <div
                className={`connection-state ${settings.data?.deepseek_has_key ? 'connected' : ''}`}
              >
                <span className="status-dot" />
                {settings.data?.deepseek_has_key ? '已保存 API Key' : '尚未配置 API Key'}
                {settings.data?.deepseek_has_key && <Check size={16} />}
              </div>
              <button
                className="button secondary"
                type="button"
                disabled={busy || checking || !settings.data?.deepseek_has_key || !!key}
                onClick={async () => {
                  setChecking(true);
                  setError('');
                  setMessage('');
                  try {
                    const result = await api<{ message: string; ocr_model_available: boolean }>(
                      '/settings/test-connection',
                      json('POST'),
                    );
                    if (result.ocr_model_available) setMessage(result.message);
                    else setError(result.message);
                  } catch (err) {
                    setError((err as Error).message);
                  } finally {
                    setChecking(false);
                  }
                }}
              >
                {checking ? '正在检查连接…' : '检查 DeepSeek 连接'}
              </button>
              <p className="field-help">
                使用已保存的密钥检查网络和模型列表，不上传教材、不消耗生成
                tokens。修改密钥后请先保存。
              </p>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  setBusy(true);
                  setError('');
                  setMessage('');
                  try {
                    await api(
                      '/settings',
                      json('PUT', {
                        api_key: key,
                        vision_thinking:
                          visionThinking || settings.data?.vision_thinking || 'enabled',
                        model: model || settings.data?.model || 'deepseek-chat',
                      }),
                    );
                    setKey('');
                    await settings.reload();
                    setMessage('设置已保存。密钥有效性会在首次识别或出题时验证。');
                  } catch (err) {
                    setError((err as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <label>
                  API Key
                  <input
                    type="password"
                    autoComplete="off"
                    value={key}
                    disabled={settings.data?.key_from_env}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder={
                      settings.data?.deepseek_has_key
                        ? '已配置 · 留空保留现有密钥'
                        : '输入 DeepSeek API Key'
                    }
                  />
                </label>
                <p className="field-help">
                  {settings.data?.key_from_env
                    ? '当前使用电脑环境变量中的密钥。请在启动环境中修改。'
                    : '密钥仅保存在本机后端，不会回传到页面或提交到 Git。'}
                </p>
                <label>
                  出题模型
                  <select
                    value={model || settings.data?.model || 'deepseek-chat'}
                    onChange={(e) => setModel(e.target.value)}
                  >
                    <option value="deepseek-chat">DeepSeek Chat · 日常练习</option>
                    <option value="deepseek-reasoner">DeepSeek Reasoner · 推理与证明</option>
                  </select>
                </label>
                <p className="field-help">
                  Chat 明确关闭思考，Reasoner 明确开启思考。复杂证明建议尝试推理模型，并核验解答。
                </p>
                <p className="field-help">
                  关闭自定义接口时，识图使用 DeepSeek Flash 并复用此密钥；出题模型的选择不影响 OCR。
                </p>
                <label>
                  原图审题思考模式
                  <select
                    value={visionThinking || settings.data?.vision_thinking || 'enabled'}
                    onChange={(e) => setVisionThinking(e.target.value)}
                  >
                    <option value="enabled">开启（默认，优先保留审题能力）</option>
                    <option value="disabled">关闭（减少思考输出，复杂题请对照核验）</option>
                  </select>
                </label>
                <p className="field-help">
                  适用于内置识图模型的原图审题和看图仿题；普通 OCR
                  始终关闭思考。关闭后的质量尚未经过大样本验证。
                </p>
                <div className="button-group">
                  <button className="button primary" type="submit" disabled={busy}>
                    <Save size={16} />
                    {busy ? '保存中…' : '保存设置'}
                  </button>
                  {settings.data?.deepseek_has_key && !settings.data.key_from_env && (
                    <button
                      className="button ghost"
                      type="button"
                      disabled={busy}
                      onClick={async () => {
                        if (!window.confirm('确认清除本机保存的 API Key？')) return;
                        try {
                          await api(
                            '/settings',
                            json('PUT', { clear_key: true, model: model || settings.data?.model }),
                          );
                          await settings.reload();
                          setMessage('已清除密钥。');
                        } catch (err) {
                          setError((err as Error).message);
                        }
                      }}
                    >
                      清除密钥
                    </button>
                  )}
                </div>
              </form>
            </section>
          </div>
          <aside>
            <div className="panel reading-note">
              <span className="eyebrow">YOUR LOCAL WORKSPACE</span>
              <h3>数据留在你的电脑上</h3>
              <div className="settings-note">
                <Server size={20} />
                <div>
                  <strong>教材与学习记录</strong>
                  <p>保存在本机 data 目录，可使用“一键备份”下载教材及学习记录。</p>
                </div>
              </div>
              <div className="settings-note">
                <ShieldCheck size={20} />
                <div>
                  <strong>API 请求范围</strong>
                  <p>
                    出题时发送相关教材文本、出题要求和已有题干；启动 OCR 时发送选定页面的图片给
                    当前选择的识图服务。
                  </p>
                </div>
              </div>
              <div className="settings-note">
                <Wifi size={20} />
                <div>
                  <strong>手机访问</strong>
                  <p>
                    手机与电脑连接同一
                    Wi-Fi，打开启动终端给出的局域网地址，并输入访问口令。电脑须保持开机。
                  </p>
                </div>
              </div>
            </div>
            <p className="field-help">
              访问口令在电脑启动终端显示。若希望自定义，可设置 STUDY_ACCESS_CODE 环境变量后重启。
            </p>
          </aside>
        </div>
      )}
    </>
  );
}
