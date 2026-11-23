import { useCallback, useEffect, useState } from 'react';
import type { Lesson } from '../types';
import { api } from '../services/api';

const CATEGORY_BADGE: Record<string, string> = {
  mistake: 'badge-rose',
  strategy: 'badge-blue',
  efficiency: 'badge-purple',
};

/** The persistent playbook across all experiments: what the memory agent knows. */
export default function PlaybookPage() {
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [showRetired, setShowRetired] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api.listLessons(showRetired)
      .then(setLessons)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [showRetired]);

  useEffect(load, [load]);

  const retire = async (id: number) => {
    try {
      await api.retireLesson(id);
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const reset = async () => {
    if (!window.confirm('Retire every lesson? The memory agent will start its next experiment with an empty playbook.')) return;
    try {
      await api.resetPlaybook();
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const active = lessons.filter((l) => l.active !== false);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Playbook</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-300">
            The memory agent's persistent knowledge. Lessons are added when it makes a mistake and after it
            reflects on each game, then ranked by how often they helped versus misled it. The strongest ones are shown
            to the agent before every move.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" className="accent-emerald-400" checked={showRetired}
                   onChange={(e) => setShowRetired(e.target.checked)} />
            Show retired
          </label>
          <button type="button" className="btn-secondary" onClick={reset} disabled={active.length === 0}>Reset playbook</button>
        </div>
      </header>

      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}

      {loading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : lessons.length === 0 ? (
        <p className="text-sm text-slate-400">No lessons yet. Run an experiment to start building the playbook.</p>
      ) : (
        <ol className="space-y-2">
          {lessons.map((lesson) => (
            <li key={lesson.id} className={`card px-4 py-3 ${lesson.active === false ? 'opacity-60' : ''}`}>
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="num text-xs font-semibold text-slate-400">L{lesson.id}</span>
                <span className={CATEGORY_BADGE[lesson.category] ?? 'badge-neutral'}>{lesson.category}</span>
                {lesson.active === false && <span className="badge-neutral">retired</span>}
                <span className="num text-xs text-slate-400">
                  score {Math.round(lesson.score * 100)} · helped {lesson.helpful} · misled {lesson.harmful} · cited {lesson.times_cited}
                </span>
                {lesson.active !== false && (
                  <button type="button" className="btn-ghost ml-auto px-2 py-1 text-xs" onClick={() => retire(lesson.id)}>
                    Retire
                  </button>
                )}
              </div>
              <p className="text-sm text-slate-200">{lesson.text}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
