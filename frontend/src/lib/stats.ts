import type { AgentKind, AgentSummary, GameRecord } from '../types';

const FINISHED = new Set(['won', 'lost', 'timeout']);

const mean = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);

/** Same aggregates as the backend's `summarize`, computed from the live games list. */
export function summarize(games: GameRecord[], recent = 20): AgentSummary {
  const finished = games.filter((g) => FINISHED.has(g.status)).sort((a, b) => a.game_index - b.game_index);
  const won = finished.filter((g) => g.status === 'won');
  const last = finished.slice(-recent);
  return {
    games_played: finished.length,
    wins: won.length,
    losses: finished.filter((g) => g.status === 'lost').length,
    timeouts: finished.filter((g) => g.status === 'timeout').length,
    win_rate: finished.length ? won.length / finished.length : null,
    recent_win_rate: last.length ? last.filter((g) => g.status === 'won').length / last.length : null,
    avg_moves_won: mean(won.map((g) => g.moves)),
    avg_min_clicks_won: mean(won.map((g) => g.min_clicks)),
    avg_efficiency_won: mean(won.map((g) => g.efficiency ?? 0)),
    avg_progress: mean(finished.map((g) => g.progress)),
    total_moves: finished.reduce((a, g) => a + g.moves, 0),
    invalid_moves: finished.reduce((a, g) => a + g.invalid_moves, 0),
    mines_hit: finished.filter((g) => g.status === 'lost').length,
    llm_calls: games.reduce((a, g) => a + g.llm_calls, 0),
    tokens: games.reduce((a, g) => a + g.prompt_tokens + g.completion_tokens, 0),
  };
}

export function byAgent(games: GameRecord[]): Record<AgentKind, GameRecord[]> {
  return {
    memory: games.filter((g) => g.agent === 'memory'),
    baseline: games.filter((g) => g.agent === 'baseline'),
  };
}

/** Win rate over a trailing window, indexed by game number (null until a game exists). */
export function rollingWinRate(games: GameRecord[], length: number, window: number): (number | null)[] {
  const byIndex = new Map(games.filter((g) => FINISHED.has(g.status)).map((g) => [g.game_index, g]));
  const out: (number | null)[] = [];
  const recent: number[] = [];
  for (let i = 0; i < length; i++) {
    const game = byIndex.get(i);
    if (!game) {
      out.push(null);
      continue;
    }
    recent.push(game.status === 'won' ? 1 : 0);
    if (recent.length > window) recent.shift();
    out.push(recent.reduce((a, b) => a + b, 0) / recent.length);
  }
  return out;
}

/** Moves used in each won game (null for games that were lost or not played yet). */
export function movesWhenWon(games: GameRecord[], length: number): (number | null)[] {
  const byIndex = new Map(games.map((g) => [g.game_index, g]));
  return Array.from({ length }, (_, i) => {
    const game = byIndex.get(i);
    return game && game.status === 'won' ? game.moves : null;
  });
}

/** Rolling mean of a sparse series, skipping nulls (smooths noisy per-game values). */
export function rollingMean(values: (number | null)[], window: number): (number | null)[] {
  const recent: number[] = [];
  return values.map((value) => {
    if (value === null) return null;
    recent.push(value);
    if (recent.length > window) recent.shift();
    return recent.reduce((a, b) => a + b, 0) / recent.length;
  });
}
