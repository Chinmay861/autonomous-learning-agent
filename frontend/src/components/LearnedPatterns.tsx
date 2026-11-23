import type { LearnedPattern, MemorySummary } from '../types';
import { compact, pct } from '../lib/format';

const INK: Record<string, string> = {
  '1': 'text-sky-300', '2': 'text-emerald-300', '3': 'text-rose-300', '4': 'text-violet-300',
  '5': 'text-amber-300', '6': 'text-cyan-300', '7': 'text-slate-100', '8': 'text-slate-300',
};

/** A 3x3 learned pattern: '?' is the hidden cell being judged. */
function MiniPattern({ rows }: { rows: string[] }) {
  return (
    <div className="grid w-14 shrink-0 grid-cols-3 gap-px rounded bg-slate-950 p-px" aria-hidden="true">
      {rows.join('').split('').map((ch, i) => {
        let cls = 'flex aspect-square items-center justify-center rounded-[2px] text-[9px] font-bold ';
        let content = '';
        if (ch === '?') {
          cls += 'bg-slate-500 text-white';
          content = '?';
        } else if (ch === '#') {
          cls += 'bg-slate-600';
        } else if (ch === '|') {
          cls += 'bg-transparent';
        } else if (ch === 'F') {
          cls += 'bg-slate-600 text-amber-300';
          content = '⚑';
        } else {
          cls += `bg-slate-800 ${INK[ch] ?? 'text-slate-500'}`;
          content = ch === '0' ? '' : ch;
        }
        return <div key={i} className={cls}>{content}</div>;
      })}
    </div>
  );
}

function describe(rows: string[]): string {
  const cells = rows.join('').replace('?', '');
  const numbers = cells.split('').filter((c) => /[1-8]/.test(c));
  const hidden = cells.split('').filter((c) => c === '#').length;
  const walls = cells.includes('|') ? ', at the board edge' : '';
  return `Hidden cell next to ${numbers.length ? `numbers ${numbers.join(', ')}` : 'no numbers'} and ${hidden} other hidden cell${hidden === 1 ? '' : 's'}${walls}`;
}

function PatternRow({ item }: { item: LearnedPattern }) {
  return (
    <li className="flex items-center gap-3">
      <MiniPattern rows={item.pattern} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2 text-xs">
          <span className="font-semibold text-slate-100 num">{pct(item.mine_rate, 1)} mine</span>
          <span className="num text-slate-400">seen {compact(item.seen)}×</span>
        </div>
        <div className="mt-1 h-1.5 rounded-full bg-slate-700" aria-hidden="true">
          <div className="h-1.5 rounded-full bg-slate-300" style={{ width: `${Math.max(2, item.mine_rate * 100)}%` }} />
        </div>
        <p className="sr-only">{describe(item.pattern)}: {pct(item.mine_rate, 1)} were mines over {item.seen} sightings.</p>
      </div>
    </li>
  );
}

interface LearnedPatternsProps {
  summary: MemorySummary | null;
  scope: 'persistent' | 'fresh';
  liveCount?: { patterns: number; observations: number } | null;
}

/** What the learning agent's memory knows: its safest and riskiest common situations. */
export function LearnedPatterns({ summary, scope, liveCount }: LearnedPatternsProps) {
  const observations = liveCount?.observations ?? summary?.observations ?? 0;
  const patterns = liveCount?.patterns ?? ((summary?.patterns_3x3 ?? 0) + (summary?.patterns_5x5 ?? 0));
  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-100">What the learning agent has learned</h2>
        <span className="meta">
          {scope === 'persistent' ? 'Persistent memory, shared across experiments' : 'Fresh memory, this experiment only'}
        </span>
      </div>
      <section className="mb-5">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Rules it discovered <span className="num normal-case text-slate-300">({summary?.rules_discovered ?? 0})</span>
        </h3>
        <p className="meta mb-2">
          Situations with two overlapping numbers that, over many games, always turned out the same way. The basic
          rules both agents share can't see these; the learning agent uses them to find safe cells and mines instead of guessing.
        </p>
        {summary && summary.rules.length ? (
          <ul className="space-y-1.5">
            {summary.rules.slice(0, 8).map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <span className={r.outcome === 'safe' ? 'badge-emerald' : 'badge-red'}>
                  {r.outcome === 'safe' ? 'always safe' : 'always a mine'}
                </span>
                <span className="text-slate-300">
                  {r.rule} <span className="num text-slate-400">· seen {compact(r.seen)}×</span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">None yet: a situation needs about 30 consistent sightings first.</p>
        )}
      </section>
      <p className="meta num mb-4">
        {compact(patterns)} situations remembered from {compact(observations)} observed cells (from both agents' games). Each tile is the 3×3
        neighbourhood of a hidden cell (<span className="text-slate-200">?</span>); the bar is how often such a cell was a mine.
      </p>
      {!summary || (summary.safest.length === 0 && summary.riskiest.length === 0) ? (
        <p className="text-sm text-slate-400">Nothing seen often enough yet. Patterns appear after a few games.</p>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2">
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Learned safe</h3>
            <ul className="space-y-2">{summary.safest.slice(0, 6).map((item, i) => <PatternRow key={i} item={item} />)}</ul>
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Learned dangerous</h3>
            <ul className="space-y-2">{summary.riskiest.slice(0, 6).map((item, i) => <PatternRow key={i} item={item} />)}</ul>
          </section>
        </div>
      )}
    </div>
  );
}
