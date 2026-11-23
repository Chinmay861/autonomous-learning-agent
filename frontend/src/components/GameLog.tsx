import { useMemo, useState } from 'react';
import type { AgentKind, GameRecord } from '../types';
import { AGENT_META, EXPERT_META } from '../lib/agents';
import { STATUS_BADGE, pct } from '../lib/format';

interface GameLogProps {
  games: GameRecord[];
  onReplay: (game: GameRecord) => void;
}

const PAGE = 25;

function Cell({ game, onReplay }: { game?: GameRecord; onReplay: (g: GameRecord) => void }) {
  if (!game) return <td className="px-3 py-2 text-slate-500">–</td>;
  if (game.agent === 'expert') {
    return (
      <td className="px-3 py-2">
        <span className="flex items-center gap-2">
          <span className={STATUS_BADGE[game.status] ?? 'badge-neutral'}>{game.status}</span>
          <span className="num text-slate-400">{game.moves} moves</span>
        </span>
      </td>
    );
  }
  return (
    <td className="px-3 py-2">
      <button type="button" onClick={() => onReplay(game)}
              className="flex items-center gap-2 rounded text-left hover:underline"
              aria-label={`Replay ${AGENT_META[game.agent].short} game ${game.game_index + 1}`}>
        <span className={STATUS_BADGE[game.status] ?? 'badge-neutral'}>{game.status}</span>
        <span className="num text-slate-200">{game.moves} moves</span>
        {game.invalid_moves > 0 && <span className="num text-xs text-rose-300">{game.invalid_moves} invalid</span>}
        {game.efficiency !== null && <span className="num text-xs text-slate-400">{pct(game.efficiency)}</span>}
      </button>
    </td>
  );
}

/** Per-game table: the same board for both agents, side by side. Doubles as the charts' table view. */
export function GameLog({ games, onReplay }: GameLogProps) {
  const [page, setPage] = useState(0);
  const rows = useMemo(() => {
    const map = new Map<number, Partial<Record<AgentKind | 'expert', GameRecord>>>();
    for (const g of games) {
      const row = map.get(g.game_index) ?? {};
      row[g.agent] = g;
      map.set(g.game_index, row);
    }
    return Array.from(map.entries()).sort((a, b) => b[0] - a[0]);
  }, [games]);
  const hasExpert = games.some((g) => g.agent === 'expert');
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const visible = rows.slice(page * PAGE, page * PAGE + PAGE);

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 pt-4">
        <h2 className="text-sm font-semibold text-slate-100">Game log</h2>
        <span className="meta">Both agents play the same board in each row. Select a result to replay it.</span>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-400">No finished games yet.</p>
      ) : (
        <>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="border-y border-slate-700 bg-slate-900/40 text-left text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Game</th>
                  <th scope="col" className="px-3 py-2 font-medium">Minimum moves</th>
                  <th scope="col" className="px-3 py-2 font-medium">{AGENT_META.memory.short}</th>
                  <th scope="col" className="px-3 py-2 font-medium">{AGENT_META.baseline.short}</th>
                  {hasExpert && <th scope="col" className="px-3 py-2 font-medium">{EXPERT_META.label}</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/60">
                {visible.map(([index, row]) => (
                  <tr key={index}>
                    <td className="num px-3 py-2 text-slate-300">{index + 1}</td>
                    <td className="num px-3 py-2 text-slate-400">{(row.memory ?? row.baseline)?.min_clicks ?? '–'}</td>
                    <Cell game={row.memory} onReplay={onReplay} />
                    <Cell game={row.baseline} onReplay={onReplay} />
                    {hasExpert && <Cell game={row.expert} onReplay={onReplay} />}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pages > 1 && (
            <div className="flex items-center justify-end gap-2 px-4 py-3 text-xs text-slate-400">
              <button type="button" className="btn-ghost px-2 py-1" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Newer
              </button>
              <span className="num">Page {page + 1} of {pages}</span>
              <button type="button" className="btn-ghost px-2 py-1" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
                Older
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
