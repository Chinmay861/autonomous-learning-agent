import { useCallback, useEffect, useState } from 'react';
import type { MemorySummary } from '../types';
import { api } from '../services/api';
import { LearnedPatterns } from '../components/LearnedPatterns';

/** The persistent memory the learning agent carries across experiments. No LLM involved. */
export default function MemoryPage() {
  const [summary, setSummary] = useState<MemorySummary | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const load = useCallback(() => {
    api.getMemory().then(setSummary).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const reset = async () => {
    if (!window.confirm('Forget everything the learning agent has learned? Its next persistent experiment starts from zero.')) return;
    try {
      const result = await api.resetMemory();
      setMessage(`Memory cleared (${result.deleted_patterns.toLocaleString()} patterns removed).`);
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Memory</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-300">
            What the learning agent has learned across all experiments that use persistent memory. For every
            situation it has seen (the board around a hidden cell) it remembers how often that cell turned out to be
            a mine or an empty region. It updates after every move and every finished game, and is saved in the database.
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={reset}
                disabled={!summary || summary.patterns_3x3 + summary.patterns_5x5 === 0}>
          Reset memory
        </button>
      </header>

      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {message && <p role="status" className="text-sm text-emerald-300">{message}</p>}

      <LearnedPatterns summary={summary} scope="persistent" />
    </div>
  );
}
