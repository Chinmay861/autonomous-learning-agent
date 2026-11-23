import type { AgentKind, AgentLive, AgentSummary } from '../types';
import { AGENT_META, LLM_DESCRIPTIONS } from '../lib/agents';
import { STATUS_BADGE, num, pct } from '../lib/format';
import { Board } from './Board';

const OUTCOME_BADGE: Record<string, string> = {
  revealed: 'badge-emerald',
  flagged: 'badge-amber',
  unflagged: 'badge-neutral',
  mine: 'badge-red',
  invalid: 'badge-rose',
};

interface AgentPanelProps {
  agent: AgentKind;
  live: AgentLive | undefined;
  summary: AgentSummary;
  numGames: number;
  agentType?: 'pattern' | 'llm';
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-slate-900/60 px-3 py-2">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="num mt-0.5 text-lg font-semibold text-slate-100">{value}</dd>
      {hint && <dd className="meta num">{hint}</dd>}
    </div>
  );
}

export function AgentPanel({ agent, live, summary, numGames, agentType = 'pattern' }: AgentPanelProps) {
  const meta = AGENT_META[agent];
  const description = agentType === 'llm' ? LLM_DESCRIPTIONS[agent] : meta.description;
  const board = live?.board;
  const move = live?.last_move;
  const gameStatus = board?.status ?? 'playing';

  return (
    <section aria-labelledby={`agent-${agent}`} className="card flex flex-col overflow-hidden">
      <header className="flex items-start justify-between gap-3 border-b border-slate-700/80 px-4 py-3"
              style={{ boxShadow: `inset 0 3px 0 ${meta.color}` }}>
        <div className="min-w-0">
          <h2 id={`agent-${agent}`} className="flex items-center gap-2 text-base font-semibold text-slate-100">
            <svg width="18" height="8" aria-hidden="true"><line x1="0" y1="4" x2="18" y2="4" stroke={meta.color} strokeWidth="3" /></svg>
            {meta.label}
          </h2>
          <p className="meta mt-0.5">{description}</p>
        </div>
        <span className={STATUS_BADGE[gameStatus] ?? 'badge-neutral'}>{gameStatus}</span>
      </header>

      <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-1 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div>
          <div className="mb-2 flex items-baseline justify-between text-xs text-slate-400">
            <span className="num">
              Game <strong className="text-slate-200">{(live?.game_index ?? 0) + 1}</strong> of {numGames}
            </span>
            {board && (
              <span className="num">
                Moves <strong className="text-slate-200">{board.moves}</strong> · min {board.min_clicks} ·
                safe {board.safe_revealed}/{board.safe_total}
              </span>
            )}
          </div>
          {board ? (
            <Board grid={board.grid} highlight={move?.action ?? null} accent={meta.color}
                   label={`${meta.label} board, game ${(live?.game_index ?? 0) + 1}, ${gameStatus}`} />
          ) : (
            <div className="flex aspect-square items-center justify-center rounded-lg bg-slate-900 text-sm text-slate-400">
              Waiting for the first game…
            </div>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          <div className="rounded-lg border border-slate-700/80 bg-slate-900/40 p-3" aria-live="polite">
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">Last move</div>
            {move ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <code className="text-sm font-semibold text-slate-100">{move.action_text}</code>
                  <span className={OUTCOME_BADGE[move.outcome] ?? 'badge-neutral'}>{move.outcome}</span>
                  {(move.turn_size ?? 1) > 1 && (
                    <span className="num text-xs text-slate-400">
                      move {(move.turn_index ?? 0) + 1} of {move.turn_size} from one LLM call
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-slate-300">{move.message}</p>
                {move.reasoning && <p className="mt-2 text-xs italic text-slate-400">“{move.reasoning}”</p>}
                {agent === 'memory' && move.lessons_used.length > 0 && (
                  <p className="mt-2 text-xs text-slate-400">
                    Used lessons: {move.lessons_used.map((id) => `L${id}`).join(', ')}
                  </p>
                )}
              </>
            ) : (
              <p className="text-xs text-slate-400">No move yet in this game.</p>
            )}
          </div>

          <dl className="grid grid-cols-2 gap-2">
            <Stat label="Win rate" value={pct(summary.win_rate)}
                  hint={`${summary.wins} of ${summary.games_played} games`} />
            <Stat label="Last 20 games" value={pct(summary.recent_win_rate)} />
            <Stat label="Moves per win" value={num(summary.avg_moves_won)}
                  hint={summary.avg_min_clicks_won !== null ? `minimum ${num(summary.avg_min_clicks_won)}` : undefined} />
            <Stat label="Efficiency" value={pct(summary.avg_efficiency_won)} hint="minimum ÷ moves, wins only" />
            <Stat label="Mines hit" value={String(summary.mines_hit)} />
            <Stat label="Invalid moves" value={String(summary.invalid_moves)}
                  hint={`${summary.total_moves} moves total`} />
          </dl>
        </div>
      </div>
    </section>
  );
}
