import type { Lesson, LessonChange } from '../types';

const CATEGORY_BADGE: Record<string, string> = {
  mistake: 'badge-rose',
  strategy: 'badge-blue',
  efficiency: 'badge-purple',
};

const CHANGE_BADGE: Record<string, string> = {
  added: 'badge-emerald',
  reinforced: 'badge-blue',
  weakened: 'badge-amber',
  revised: 'badge-purple',
  retired: 'badge-neutral',
};

export interface ActivityItem {
  id: string;
  kind: 'lesson' | 'mistake' | 'analysis' | 'error';
  /** Zero-based game index, when the item belongs to a game. */
  game?: number;
  text: string;
  tag?: string;
}

interface PlaybookPanelProps {
  lessons: Lesson[];
  recentChanges: Record<number, LessonChange['type']>;
  activity: ActivityItem[];
  scope: 'persistent' | 'fresh';
}

export function PlaybookPanel({ lessons, recentChanges, activity, scope }: PlaybookPanelProps) {
  return (
    <section className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="card p-4">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-100">Memory agent's playbook</h2>
          <span className="meta">
            {scope === 'persistent' ? 'Persistent: includes lessons from earlier experiments' : 'Fresh: only lessons from this experiment'}
          </span>
        </div>
        {lessons.length === 0 ? (
          <p className="text-sm text-slate-400">
            No lessons yet. They appear as the memory agent makes mistakes and reflects after each game.
          </p>
        ) : (
          <ol className="space-y-2">
            {lessons.map((lesson, i) => (
              <li key={lesson.id} className="rounded-lg border border-slate-700/70 bg-slate-900/40 px-3 py-2">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="num text-xs font-semibold text-slate-400">#{i + 1} · L{lesson.id}</span>
                  <span className={CATEGORY_BADGE[lesson.category] ?? 'badge-neutral'}>{lesson.category}</span>
                  {recentChanges[lesson.id] && (
                    <span className={CHANGE_BADGE[recentChanges[lesson.id]]}>{recentChanges[lesson.id]}</span>
                  )}
                  <span className="num ml-auto text-xs text-slate-400">
                    helped {lesson.helpful} · misled {lesson.harmful} · cited {lesson.times_cited}
                  </span>
                </div>
                <p className="text-sm text-slate-200">{lesson.text}</p>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="card p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Learning activity</h2>
        {activity.length === 0 ? (
          <p className="text-sm text-slate-400">Mistakes, reflections and playbook changes stream in here.</p>
        ) : (
          <ul className="max-h-[28rem] space-y-2 overflow-y-auto pr-1" aria-live="polite">
            {activity.map((item) => (
              <li key={item.id} className="text-xs">
                <div className="mb-0.5 flex items-center gap-2">
                  {item.game !== undefined && <span className="num text-slate-400">Game {item.game + 1}</span>}
                  {item.tag && (
                    <span className={
                      item.kind === 'mistake' ? 'badge-rose'
                        : item.kind === 'error' ? 'badge-red'
                          : item.kind === 'analysis' ? 'badge-purple'
                            : CHANGE_BADGE[item.tag] ?? 'badge-neutral'
                    }>{item.tag}</span>
                  )}
                </div>
                <p className="text-slate-300">{item.text}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
