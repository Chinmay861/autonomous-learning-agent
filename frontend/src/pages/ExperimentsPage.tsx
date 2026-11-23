import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { Experiment, Options } from '../types';
import { api } from '../services/api';
import { AGENT_META } from '../lib/agents';
import { STATUS_BADGE, modelLabel, pct } from '../lib/format';

const CUSTOM_MODEL = '__custom__';

const PRESET_LABELS: Record<string, string> = {
  small: 'Small',
  beginner: 'Beginner',
  intermediate: 'Intermediate',
};

export default function ExperimentsPage() {
  const navigate = useNavigate();
  const [options, setOptions] = useState<Options | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    name: '',
    preset: 'beginner',
    num_games: 500,
    agent_type: 'pattern' as 'pattern' | 'llm',
    speed: 'watch' as 'watch' | 'fast',
    model: '',
    customModel: '',
    temperature: 0.3,
    memory_scope: 'persistent' as 'persistent' | 'fresh',
    base_seed: '',
  });

  useEffect(() => {
    Promise.all([api.getOptions().catch(() => null), api.listExperiments()])
      .then(([opts, list]) => {
        if (opts) {
          setOptions(opts);
          setForm((f) => ({ ...f, model: opts.default_model, num_games: opts.default_num_games, temperature: opts.default_temperature }));
        }
        setExperiments(list);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      const created = await api.createExperiment({
        name: form.name.trim() || undefined,
        preset: form.preset,
        num_games: form.num_games,
        agent_type: form.agent_type,
        speed: form.speed,
        ...(form.agent_type === 'llm' ? {
          model: (form.model === CUSTOM_MODEL ? form.customModel : form.model).trim() || undefined,
          temperature: form.temperature,
        } : {}),
        memory_scope: form.memory_scope,
        base_seed: form.base_seed.trim() ? Number(form.base_seed) : undefined,
        start: true,
      });
      navigate(`/experiments/${created.id}`);
    } catch (err: any) {
      setError(err.message);
      setSubmitting(false);
    }
  };

  const preset = options?.presets[form.preset];
  const estimate = preset ? Math.round(form.num_games * 2 * (preset.rows * preset.cols - preset.mines) * 0.4) : null;
  const isLlm = form.agent_type === 'llm';

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">Minesweeper learning experiments</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-300">
          Two agents play the same sequence of Minesweeper boards side by side, using no LLM. Both reason from
          the numbers on the board to find certain moves and both try to win every game. When reasoning runs
          out, one of them also uses its persistent memory: everything learned from past games, its own and
          the other agent's, including every mistake. The other agent never uses memory and figures each game
          out on its own. The rules of the game are enforced by the game engine itself.
        </p>
      </header>

      <form onSubmit={submit} className="card grid gap-5 p-5 md:grid-cols-2" aria-labelledby="new-exp">
        <h2 id="new-exp" className="text-base font-semibold text-slate-100 md:col-span-2">New experiment</h2>

        <fieldset className="md:col-span-2">
          <legend className="label">Board</legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {Object.entries(options?.presets ?? { small: { rows: 6, cols: 6, mines: 5 }, beginner: { rows: 9, cols: 9, mines: 10 }, intermediate: { rows: 16, cols: 16, mines: 40 } })
              .map(([key, p]) => (
                <label key={key}
                       className={`cursor-pointer rounded-lg border px-3 py-2 text-sm ${form.preset === key ? 'border-emerald-400 bg-emerald-950/40' : 'border-slate-700 bg-slate-900'}`}>
                  <input type="radio" name="preset" value={key} checked={form.preset === key} className="sr-only"
                         onChange={() => setForm({ ...form, preset: key })} />
                  <span className="font-semibold text-slate-100">{PRESET_LABELS[key] ?? key}</span>
                  <span className="num block text-xs text-slate-400">{p.rows}×{p.cols}, {p.mines} mines</span>
                </label>
              ))}
          </div>
          <span className="hint">Bigger boards need more guessing, which is where memory helps: learning shows most on Intermediate.</span>
        </fieldset>

        <div>
          <label htmlFor="num_games" className="label">Games per agent</label>
          <input id="num_games" type="number" min={1} max={options?.max_num_games ?? 5000} className="input num"
                 value={form.num_games} onChange={(e) => setForm({ ...form, num_games: Number(e.target.value) || 1 })} />
          <span className="hint num">
            {isLlm
              ? (estimate !== null && `Roughly ${estimate.toLocaleString()} LLM calls in total.`)
              : 'No LLM is used, so there are no limits: Fast mode plays hundreds of games a minute.'}
          </span>
        </div>

        <fieldset>
          <legend className="label">Speed</legend>
          <div className="space-y-2 text-sm">
            <label className="flex items-start gap-2">
              <input type="radio" name="speed" className="mt-1 accent-emerald-400" checked={form.speed === 'watch'}
                     onChange={() => setForm({ ...form, speed: 'watch' })} />
              <span><span className="text-slate-100">Watch</span>
                <span className="hint mt-0">Paced so you can follow every move on both boards.</span></span>
            </label>
            <label className="flex items-start gap-2">
              <input type="radio" name="speed" className="mt-1 accent-emerald-400" checked={form.speed === 'fast'}
                     onChange={() => setForm({ ...form, speed: 'fast' })} />
              <span><span className="text-slate-100">Fast</span>
                <span className="hint mt-0">As fast as possible; the boards update a few times a second. Switchable while running.</span></span>
            </label>
          </div>
        </fieldset>

        {options?.llm_enabled && (
          <div>
            <label htmlFor="agent_type" className="label">Agents</label>
            <select id="agent_type" className="input" value={form.agent_type}
                    onChange={(e) => setForm({ ...form, agent_type: e.target.value as 'pattern' | 'llm' })}>
              <option value="pattern">Code-only learning agents (no LLM)</option>
              <option value="llm">LLM agents</option>
            </select>
          </div>
        )}

        {isLlm && (
        <div>
          <label htmlFor="model" className="label">Model</label>
          <select id="model" className="input" value={form.model}
                  onChange={(e) => setForm({ ...form, model: e.target.value })}>
            {(options?.model_groups ?? []).map((group) => (
              <optgroup key={group.provider} label={group.label}>
                {group.models.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}{m.value === options?.default_model ? ' (default)' : ''}
                  </option>
                ))}
              </optgroup>
            ))}
            {!options?.model_groups.length && form.model && form.model !== CUSTOM_MODEL && (
              <option value={form.model}>{modelLabel(form.model)}</option>
            )}
            <option value={CUSTOM_MODEL}>Other model…</option>
          </select>
          {form.model === CUSTOM_MODEL && (
            <input aria-label="Custom model name" className="input mt-2" value={form.customModel}
                   placeholder="e.g. groq:llama-3.3-70b-versatile or ollama:qwen3:4b"
                   onChange={(e) => setForm({ ...form, customModel: e.target.value })} />
          )}
          <span className="hint">Both agents use the same model, so the only difference between them is memory.</span>
        </div>
        )}

        <fieldset>
          <legend className="label">Learning agent starts from</legend>
          <div className="space-y-2 text-sm">
            <label className="flex items-start gap-2">
              <input type="radio" name="scope" className="mt-1 accent-emerald-400" checked={form.memory_scope === 'persistent'}
                     onChange={() => setForm({ ...form, memory_scope: 'persistent' })} />
              <span><span className="text-slate-100">Everything it has learned before</span>
                <span className="hint mt-0">Its persistent memory, carried over from earlier experiments.</span></span>
            </label>
            <label className="flex items-start gap-2">
              <input type="radio" name="scope" className="mt-1 accent-emerald-400" checked={form.memory_scope === 'fresh'}
                     onChange={() => setForm({ ...form, memory_scope: 'fresh' })} />
              <span><span className="text-slate-100">An empty memory</span>
                <span className="hint mt-0">Only uses what it learns in this experiment: shows learning from zero.</span></span>
            </label>
          </div>
        </fieldset>

        <div className="grid grid-cols-2 gap-3">
          {isLlm && (
            <div>
              <label htmlFor="temperature" className="label">Temperature</label>
              <input id="temperature" type="number" step="0.1" min={0} max={2} className="input num" value={form.temperature}
                     onChange={(e) => setForm({ ...form, temperature: Number(e.target.value) })} />
            </div>
          )}
          <div>
            <label htmlFor="seed" className="label">Seed (optional)</label>
            <input id="seed" inputMode="numeric" className="input num" value={form.base_seed} placeholder="random"
                   onChange={(e) => setForm({ ...form, base_seed: e.target.value.replace(/\D/g, '') })} />
          </div>
          <div className="col-span-2">
            <label htmlFor="name" className="label">Name (optional)</label>
            <input id="name" className="input" value={form.name} maxLength={200}
                   onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
        </div>

        {error && <p role="alert" className="text-sm text-red-300 md:col-span-2">{error}</p>}
        <div className="md:col-span-2">
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'Starting…' : 'Start both agents'}
          </button>
        </div>
      </form>

      <section aria-labelledby="past">
        <h2 id="past" className="mb-3 text-base font-semibold text-slate-100">Experiments</h2>
        {loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : experiments.length === 0 ? (
          <p className="text-sm text-slate-400">No experiments yet. Start one above.</p>
        ) : (
          <ul className="grid gap-3 md:grid-cols-2">
            {experiments.map((exp) => (
              <li key={exp.id}>
                <Link to={`/experiments/${exp.id}`} className="card block p-4 transition-colors hover:border-slate-500">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-slate-100">{exp.name}</div>
                      <div className="meta num mt-0.5">
                        {exp.rows}×{exp.cols}/{exp.mines} · {exp.agent_type === 'llm' ? modelLabel(exp.model) : 'no LLM'} · {exp.memory_scope} memory
                      </div>
                    </div>
                    <span className={STATUS_BADGE[exp.status] ?? 'badge-neutral'}>{exp.status}</span>
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                    {(['memory', 'baseline'] as const).map((agent) => {
                      const s = exp.summary?.[agent];
                      return (
                        <div key={agent} className="rounded-lg bg-slate-900/60 px-3 py-2">
                          <dt className="flex items-center gap-1.5 text-xs text-slate-400">
                            <svg width="14" height="6" aria-hidden="true"><line x1="0" y1="3" x2="14" y2="3" stroke={AGENT_META[agent].color} strokeWidth="2" /></svg>
                            {AGENT_META[agent].short}
                          </dt>
                          <dd className="num font-semibold text-slate-100">
                            {pct(s?.win_rate ?? null)} won
                            <span className="ml-1 text-xs font-normal text-slate-400">
                              {s?.games_played ?? 0}/{exp.num_games} games
                            </span>
                          </dd>
                        </div>
                      );
                    })}
                  </dl>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
