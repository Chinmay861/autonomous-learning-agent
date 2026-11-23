import type { ActivityItem } from './PlaybookPanel';

const TAG_BADGE: Record<ActivityItem['kind'], string> = {
  mistake: 'badge-rose',
  error: 'badge-red',
  analysis: 'badge-purple',
  lesson: 'badge-blue',
};

/** Live feed of mistakes and learning events, newest first. */
export function ActivityFeed({ items, empty }: { items: ActivityItem[]; empty: string }) {
  return (
    <div className="card p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">Learning activity</h2>
      {items.length === 0 ? (
        <p className="text-sm text-slate-400">{empty}</p>
      ) : (
        <ul className="max-h-[28rem] space-y-2 overflow-y-auto pr-1" aria-live="polite">
          {items.map((item) => (
            <li key={item.id} className="text-xs">
              <div className="mb-0.5 flex items-center gap-2">
                <span className="num text-slate-400">Game {item.game + 1}</span>
                {item.tag && <span className={TAG_BADGE[item.kind]}>{item.tag}</span>}
              </div>
              <p className="text-slate-300">{item.text}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
