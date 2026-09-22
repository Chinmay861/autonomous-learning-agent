import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { Settings } from '../types';

type Notice = { kind: 'success' | 'error'; text: string } | null;

const SettingsPage = () => {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const showNotice = (kind: 'success' | 'error', text: string) => {
    setNotice({ kind, text });
    if (kind === 'success') {
      window.setTimeout(() => setNotice(current => (current?.text === text ? null : current)), 3500);
    }
  };

  const fetchData = async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [settingsData, modelsData] = await Promise.all([
        api.getSettings(),
        api.listModels().catch(() => [])
      ]);
      setSettings(settingsData);
      setModels(modelsData);
    } catch (err: any) {
      setLoadError(err?.message || 'Unable to load settings. Check the connection and try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!settings) return;

    setSaving(true);
    setNotice(null);
    try {
      await api.updateSettings(settings);
      showNotice('success', 'Settings saved.');
    } catch (err: any) {
      showNotice('error', err?.message || 'Unable to save settings. Check the connection and try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleTogglePersistentLearning = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!settings) return;
    const checked = e.target.checked;
    const updated = { ...settings, persistent_learning_enabled: checked };
    setSettings(updated);
    try {
      await api.updateSettings(updated);
      showNotice('success', checked ? 'Stored learnings will be retrieved.' : 'Stored learnings will be ignored.');
    } catch (err: any) {
      setSettings(settings);
      showNotice('error', err?.message || 'Unable to save this setting. Check the connection and try again.');
    }
  };

  if (loading) {
    return (
      <div role="status" className="py-16 text-center text-sm text-slate-400">
        Loading settings…
      </div>
    );
  }

  if (!settings) {
    return (
      <div role="alert" className="mx-auto max-w-xl rounded-lg border border-red-700/60 bg-red-950 px-4 py-3 text-sm text-red-200">
        <p>{loadError || 'Unable to load settings.'}</p>
        <button type="button" onClick={fetchData} className="btn-secondary mt-3 px-3 py-1.5 text-xs">
          Try again
        </button>
      </div>
    );
  }

  const missingKey =
    (settings.llm_provider === 'groq' && !settings.has_groq_key) ||
    (settings.llm_provider === 'gemini' && !settings.has_gemini_key) ||
    (settings.llm_provider === 'openai' && !settings.has_openai_key) ||
    (settings.llm_provider === 'openrouter' && !settings.has_openrouter_key);

  const providerName =
    settings.llm_provider === 'groq' ? 'Groq' :
    settings.llm_provider === 'gemini' ? 'Google Gemini' :
    settings.llm_provider === 'openai' ? 'OpenAI' :
    settings.llm_provider === 'openrouter' ? 'OpenRouter' : 'Ollama';

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {notice && (
        <div
          role={notice.kind === 'error' ? 'alert' : 'status'}
          className={`flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm ${
            notice.kind === 'error'
              ? 'border-red-700/60 bg-red-950 text-red-200'
              : 'border-emerald-700/60 bg-emerald-950 text-emerald-200'
          }`}
        >
          <span>{notice.text}</span>
          {notice.kind === 'error' && (
            <button
              type="button"
              onClick={() => setNotice(null)}
              className="shrink-0 font-semibold underline underline-offset-2"
            >
              Dismiss
            </button>
          )}
        </div>
      )}

      <form onSubmit={handleSave} className="card space-y-6 p-5 sm:p-6">
        <section aria-labelledby="defaults-heading">
          <h2 id="defaults-heading" className="mb-4 border-b border-slate-700 pb-2 text-lg font-semibold text-emerald-300">
            Defaults
          </h2>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div>
              <label htmlFor="settings-model" className="label">
                Default model
              </label>
              <select
                id="settings-model"
                value={settings.default_model}
                onChange={e => setSettings({ ...settings, default_model: e.target.value })}
                className="input"
              >
                {(models || []).map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>

            <div>
              <label htmlFor="settings-tool-permissions" className="label">
                Tool permissions
              </label>
              <select
                id="settings-tool-permissions"
                value={settings.tool_permissions}
                onChange={e => setSettings({ ...settings, tool_permissions: e.target.value })}
                className="input"
              >
                <option value="none">None (view only)</option>
                <option value="safe">Safe (read-only tools)</option>
                <option value="all">All (write access)</option>
              </select>
            </div>

            <div>
              <label htmlFor="settings-max-iterations" className="label">
                Default iteration limit
              </label>
              <input
                id="settings-max-iterations"
                type="number"
                min={1}
                step={1}
                value={settings.default_max_iterations}
                onChange={e => setSettings({ ...settings, default_max_iterations: parseInt(e.target.value) })}
                className="input"
              />
            </div>

            <div>
              <label htmlFor="settings-snapshot-interval" className="label">
                Snapshot interval
              </label>
              <input
                id="settings-snapshot-interval"
                type="number"
                min={1}
                step={1}
                value={settings.default_snapshot_interval}
                onChange={e => setSettings({ ...settings, default_snapshot_interval: parseInt(e.target.value) })}
                className="input"
              />
            </div>

            <div>
              <label htmlFor="settings-synthesis-interval" className="label">
                Synthesis interval
              </label>
              <input
                id="settings-synthesis-interval"
                type="number"
                min={1}
                step={1}
                value={settings.default_synthesis_interval}
                onChange={e => setSettings({ ...settings, default_synthesis_interval: parseInt(e.target.value) })}
                className="input"
              />
            </div>
          </div>
        </section>

        <section aria-labelledby="provider-heading">
          <h2 id="provider-heading" className="mb-4 border-b border-slate-700 pb-2 text-lg font-semibold text-emerald-300">
            Model provider
          </h2>
          <div className="space-y-4">
            <div>
              <label htmlFor="settings-provider" className="label">
                Provider
              </label>
              <select
                id="settings-provider"
                value={settings.llm_provider || 'ollama'}
                onChange={e => {
                  const prov = e.target.value;
                  let defModel = settings.default_model;
                  if (prov === 'groq') defModel = 'groq/llama-3.3-70b-versatile';
                  else if (prov === 'gemini') defModel = 'gemini/gemini-2.0-flash';
                  else if (prov === 'openai') defModel = 'openai/gpt-4o-mini';
                  else if (prov === 'openrouter') defModel = 'openrouter/meta-llama/llama-3.3-70b-instruct';
                  else if (prov === 'ollama') defModel = 'qwen3:4b';
                  setSettings({
                    ...settings,
                    llm_provider: prov,
                    default_model: defModel,
                    cloud_model: defModel
                  });
                }}
                className="input"
              >
                <option value="ollama">Local Ollama (runs on localhost:11434)</option>
                <option value="groq">Groq (cloud)</option>
                <option value="gemini">Google Gemini (cloud)</option>
                <option value="openai">OpenAI (cloud)</option>
                <option value="openrouter">OpenRouter (cloud)</option>
              </select>
            </div>

            <div className="rounded-lg border border-slate-700 bg-slate-900/80 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-semibold text-slate-200">{providerName}</span>
                {(!settings.llm_provider || settings.llm_provider === 'ollama') ? (
                  <span className="badge-blue">Local service</span>
                ) : missingKey ? (
                  <span className="badge-amber">No key found</span>
                ) : (
                  <span className="badge-emerald">Key found</span>
                )}
              </div>

              {(!settings.llm_provider || settings.llm_provider === 'ollama') ? (
                <p className="mt-3 text-sm text-slate-400">
                  Runs on this machine at <code className="text-emerald-300">http://localhost:11434</code>. No API key needed.
                </p>
              ) : (
                <div className="mt-3 space-y-2 text-sm text-slate-300">
                  <p className="text-slate-400">
                    API keys live in <code className="text-emerald-300">backend/.env</code> and are never stored in the browser.
                  </p>
                  <p className="text-slate-400">
                    {missingKey
                      ? `Add this line to backend/.env, then restart the backend:`
                      : `Key detected. Update it in backend/.env:`}
                  </p>
                  <pre className="select-all overflow-x-auto rounded border border-slate-800 bg-slate-950 p-2.5 font-mono text-xs text-emerald-300">
                    {settings.llm_provider === 'groq' && 'GROQ_API_KEY=gsk_your_groq_api_key_here'}
                    {settings.llm_provider === 'gemini' && 'GEMINI_API_KEY=AIza_your_gemini_api_key_here'}
                    {settings.llm_provider === 'openai' && 'OPENAI_API_KEY=sk_your_openai_api_key_here'}
                    {settings.llm_provider === 'openrouter' && 'OPENROUTER_API_KEY=sk-or_your_openrouter_api_key_here'}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </section>

        <section aria-labelledby="learning-heading">
          <h2 id="learning-heading" className="mb-4 border-b border-slate-700 pb-2 text-lg font-semibold text-emerald-300">
            Learning system
          </h2>
          <label htmlFor="settings-persistent-learning" className="flex cursor-pointer select-none items-start gap-3">
            <input
              id="settings-persistent-learning"
              type="checkbox"
              checked={Boolean(settings.persistent_learning_enabled)}
              onChange={handleTogglePersistentLearning}
              className="mt-0.5 h-5 w-5 rounded border-slate-600 bg-slate-900 accent-emerald-600"
            />
            <span>
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-200">Retrieve stored learnings</span>
                <span className={settings.persistent_learning_enabled ? 'badge-emerald' : 'badge-neutral'}>
                  {settings.persistent_learning_enabled ? 'On' : 'Off'}
                </span>
              </span>
              <span className="hint mt-1 block">
                When on, runs retrieve relevant knowledge from earlier tasks. Learning and storage always continue, in both states. Changes save automatically.
              </span>
            </span>
          </label>
        </section>

        <div className="flex justify-end border-t border-slate-700 pt-4">
          <button type="submit" disabled={saving} className="btn-primary">
            {saving ? 'Saving…' : 'Save settings'}
          </button>
        </div>
      </form>
    </div>
  );
};

export default SettingsPage;
