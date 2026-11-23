export interface User {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
}

export type AgentKind = 'memory' | 'baseline';
export const AGENTS: AgentKind[] = ['memory', 'baseline'];

export type ExperimentStatus =
  | 'created' | 'running' | 'paused' | 'completed' | 'stopped' | 'failed' | 'interrupted';

export type GameStatus = 'playing' | 'won' | 'lost' | 'timeout';

export interface Board {
  rows: number;
  cols: number;
  mines: number;
  grid: string[];
  status: GameStatus | string;
  moves: number;
  max_moves: number;
  safe_revealed: number;
  safe_total: number;
  min_clicks: number;
  flags?: number;
  invalid_moves?: number;
  exploded?: [number, number] | null;
}

export interface CellAction {
  action: string;
  row: number;
  col: number;
}

export interface MoveEvent {
  move_index: number;
  action: CellAction | null;
  action_text: string;
  reasoning: string;
  outcome: 'revealed' | 'flagged' | 'unflagged' | 'mine' | 'invalid' | string;
  valid: boolean;
  message: string;
  lessons_used: number[];
  /** Position within the turn: several moves can come from one LLM call. */
  turn_index?: number;
  turn_size?: number;
}

export interface Lesson {
  id: number;
  text: string;
  category: 'mistake' | 'strategy' | 'efficiency' | string;
  helpful: number;
  harmful: number;
  times_cited: number;
  score: number;
  active?: boolean;
  experiment_id?: string | null;
  created_at?: string;
}

export interface LessonChange {
  type: 'added' | 'reinforced' | 'weakened' | 'revised' | 'retired';
  id: number;
  text: string;
}

export interface AgentLive {
  game_index: number;
  game_id: number | null;
  board: Board;
  last_move: MoveEvent | null;
  lessons?: Lesson[];
}

export interface AgentSummary {
  games_played: number;
  wins: number;
  losses: number;
  timeouts: number;
  win_rate: number | null;
  recent_win_rate: number | null;
  avg_moves_won: number | null;
  avg_min_clicks_won: number | null;
  avg_efficiency_won: number | null;
  avg_progress: number | null;
  total_moves: number;
  invalid_moves: number;
  mines_hit: number;
  llm_calls: number;
  tokens: number;
}

export interface Experiment {
  id: string;
  name: string;
  rows: number;
  cols: number;
  mines: number;
  num_games: number;
  max_moves: number;
  base_seed: number;
  model: string;
  temperature: number;
  memory_scope: 'persistent' | 'fresh';
  /** 'pattern' = code-only learning agents (no LLM); 'llm' = the LLM agents (disabled by default). */
  agent_type: 'pattern' | 'llm';
  speed: 'watch' | 'fast';
  status: ExperimentStatus;
  is_active: boolean;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  /** Includes 'expert' (hand-written rules, reference only) for code-only experiments. */
  summary?: Partial<Record<AgentKind | 'expert', AgentSummary>>;
  current?: Record<AgentKind, AgentLive>;
}

export interface Mistake {
  move: number;
  type: string;
  action: CellAction | null;
  reasoning: string;
  message: string;
  /** Code-only agents: how risky the agent believed the cell was when it chose it. */
  estimated_risk?: number;
}

export interface GameRecord {
  id: number;
  agent: AgentKind | 'expert';
  game_index: number;
  seed: number;
  status: GameStatus;
  moves: number;
  reveals: number;
  flag_moves: number;
  invalid_moves: number;
  min_clicks: number;
  efficiency: number | null;
  safe_revealed: number;
  safe_total: number;
  progress: number;
  llm_calls: number;
  llm_errors: number;
  prompt_tokens: number;
  completion_tokens: number;
  lessons_available: number;
  lessons_cited: number[];
  mistakes: Mistake[];
  final_grid: string[];
  duration_ms: number;
}

export interface ReplayMove {
  move_index: number;
  action: CellAction | null;
  reasoning: string | null;
  outcome: string;
  valid: boolean;
  message: string;
  grid_after: string[];
}

export interface ModelGroup {
  provider: string;
  label: string;
  models: { value: string; label: string }[];
}

export interface Options {
  llm_enabled: boolean;
  default_model: string;
  provider: string;
  model_groups: ModelGroup[];
  models: string[];
  presets: Record<string, { rows: number; cols: number; mines: number }>;
  default_num_games: number;
  max_num_games: number;
  default_temperature: number;
}

export interface ExperimentCreate {
  name?: string;
  preset?: string;
  num_games: number;
  model?: string;
  temperature?: number;
  memory_scope: 'persistent' | 'fresh';
  agent_type?: 'pattern' | 'llm';
  speed?: 'watch' | 'fast';
  base_seed?: number;
  start?: boolean;
}

export interface LearnedPattern {
  /** 3x3 rows around a hidden cell ('?'), as the agent saw it: '#' hidden, '0'-'8' numbers, '|' wall. */
  pattern: string[];
  seen: number;
  mine_rate: number;
  zero_rate: number;
}

export interface DiscoveredRule {
  /** Plain-language description of the overlapping-number situation. */
  rule: string;
  outcome: 'safe' | 'mine';
  seen: number;
}

export interface MemorySummary {
  bank: string;
  rules_discovered: number;
  rules: DiscoveredRule[];
  patterns_3x3: number;
  patterns_5x5: number;
  observations: number;
  safest: LearnedPattern[];
  riskiest: LearnedPattern[];
}

/** Events pushed over /ws/experiments/{id}. */
export type ExperimentEvent =
  | { type: 'heartbeat' }
  | { type: 'experiment_status'; status: ExperimentStatus; error: string | null }
  | { type: 'game_started'; agent: AgentKind; game_index: number; game_id: number; board: Board; lessons: Lesson[] }
  | ({ type: 'move'; agent: AgentKind; game_index: number; game_id: number; board: Board } & MoveEvent)
  | { type: 'game_finished'; agent: AgentKind | 'expert'; game_index: number; game: GameRecord; board?: Board; analysis: string | null }
  | { type: 'memory_updated'; game_index?: number; patterns: number; observations: number; new_patterns?: number;
      mistake?: Mistake | null; mistakes?: (Mistake & { agent: AgentKind })[]; learned_from?: Record<AgentKind, number>;
      rules?: number; new_rules?: DiscoveredRule[] }
  | { type: 'game_aborted'; agent: AgentKind; game_index: number }
  | { type: 'lessons_updated'; agent: AgentKind; game_index: number; changes: LessonChange[]; lessons: Lesson[]; analysis?: string | null }
  | { type: 'agent_error'; agent: AgentKind; game_index: number; error: string }
  | { type: 'runner_restarted'; reason: string; attempt: number; delay: number };
