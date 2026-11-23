import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type {
  AgentKind, AgentLive, Experiment, ExperimentEvent, GameRecord, Lesson, LessonChange, MemorySummary,
} from '../types';
import { AGENTS } from '../types';
import { api } from '../services/api';
import { ExperimentSocket } from '../services/websocket';
import { AGENT_META, EXPERT_META } from '../lib/agents';
import { movesWhenWon, rollingMean, rollingWinRate, summarize } from '../lib/stats';
import { STATUS_BADGE, compact, modelLabel, num, pct } from '../lib/format';
import { AgentPanel } from '../components/AgentPanel';
import { LineChart, type Series } from '../components/LineChart';
import { PlaybookPanel, type ActivityItem } from '../components/PlaybookPanel';
import { LearnedPatterns } from '../components/LearnedPatterns';
import { ActivityFeed } from '../components/ActivityFeed';
import { GameLog } from '../components/GameLog';
import { ReplayDialog } from '../components/ReplayDialog';

const ACTIVITY_LIMIT = 60;
// Finished games arrive many times a second in fast mode; batch them into one update.
const GAME_FLUSH_MS = 500;
const MEMORY_REFRESH_MS = 4000;

export default function ExperimentPage() {
  const { experimentId = '' } = useParams();
  const navigate = useNavigate();
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [games, setGames] = useState<GameRecord[]>([]);
  const [live, setLive] = useState<Partial<Record<AgentKind, AgentLive>>>({});
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [recentChanges, setRecentChanges] = useState<Record<number, LessonChange['type']>>({});
  const [memory, setMemory] = useState<MemorySummary | null>(null);
  const [memoryCount, setMemoryCount] = useState<{ patterns: number; observations: number } | null>(null);
  const [learnedFrom, setLearnedFrom] = useState<Record<AgentKind, number> | null>(null);
  const [rulesCount, setRulesCount] = useState<number | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [replay, setReplay] = useState<GameRecord | null>(null);
  const activitySeq = useRef(0);
  const pendingGames = useRef<GameRecord[]>([]);
  const lastMemoryFetch = useRef(0);

  const isCodeOnly = experiment ? experiment.agent_type !== 'llm' : true;

  const pushActivity = useCallback((item: Omit<ActivityItem, 'id'>) => {
    activitySeq.current += 1;
    const entry = { ...item, id: `a${activitySeq.current}` };
    setActivity((prev) => [entry, ...prev].slice(0, ACTIVITY_LIMIT));
  }, []);

  const refreshMemory = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && now - lastMemoryFetch.current < MEMORY_REFRESH_MS) return;
    lastMemoryFetch.current = now;
    try {
      setMemory(await api.getExperimentMemory(experimentId));
    } catch {
      /* the panel keeps its previous contents */
    }
  }, [experimentId]);

  const load = useCallback(async () => {
    try {
      const [exp, gameList] = await Promise.all([api.getExperiment(experimentId), api.listGames(experimentId)]);
      setExperiment(exp);
      setGames(gameList);
      if (exp.current) setLive(exp.current);
      if (exp.agent_type === 'llm') {
        const memoryLessons = exp.current?.memory?.lessons;
        if (memoryLessons) {
          setLessons(memoryLessons);
        } else {
          const all = await api.listLessons();
          setLessons(exp.memory_scope === 'fresh' ? all.filter((l) => l.experiment_id === exp.id) : all);
        }
      } else {
        refreshMemory(true);
      }
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  }, [experimentId, refreshMemory]);

  useEffect(() => { load(); }, [load]);

  // Flush batched finished games.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!pendingGames.current.length) return;
      const batch = pendingGames.current;
      pendingGames.current = [];
      setGames((prev) => {
        const key = (g: GameRecord) => `${g.agent}:${g.game_index}`;
        const incoming = new Set(batch.map(key));
        return [...prev.filter((g) => !incoming.has(key(g))), ...batch];
      });
    }, GAME_FLUSH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const handleEvent = useCallback((event: ExperimentEvent) => {
    switch (event.type) {
      case 'experiment_status':
        setExperiment((prev) => (prev ? { ...prev, status: event.status, error: event.error, is_active: ['running', 'paused'].includes(event.status) } : prev));
        if (event.error) pushActivity({ kind: 'error', game: 0, tag: 'stopped', text: event.error });
        if (['completed', 'stopped', 'failed'].includes(event.status)) load();
        break;
      case 'game_started':
        setLive((prev) => ({ ...prev, [event.agent]: { game_index: event.game_index, game_id: event.game_id, board: event.board, last_move: null } }));
        if (event.agent === 'memory' && event.lessons.length) setLessons(event.lessons);
        break;
      case 'move':
        setLive((prev) => ({
          ...prev,
          [event.agent]: {
            game_index: event.game_index,
            game_id: event.game_id,
            board: event.board,
            last_move: {
              move_index: event.move_index, action: event.action, action_text: event.action_text,
              reasoning: event.reasoning, outcome: event.outcome, valid: event.valid,
              message: event.message, lessons_used: event.lessons_used,
              turn_index: event.turn_index, turn_size: event.turn_size,
            },
          },
        }));
        if (!event.valid || event.outcome === 'mine') {
          pushActivity({
            kind: 'mistake', game: event.game_index,
            tag: `${AGENT_META[event.agent].short}: ${event.outcome === 'mine' ? 'mine hit' : 'invalid move'}`,
            text: `${event.action_text}: ${event.message}`,
          });
        }
        break;
      case 'game_finished':
        pendingGames.current.push(event.game);
        if (event.agent !== 'expert' && event.board) {
          const board = event.board;
          setLive((prev) => {
            const current = prev[event.agent as AgentKind];
            return current ? { ...prev, [event.agent]: { ...current, board } } : prev;
          });
        }
        break;
      case 'memory_updated':
        setMemoryCount({ patterns: event.patterns, observations: event.observations });
        if (event.learned_from) setLearnedFrom(event.learned_from);
        if (event.rules !== undefined) setRulesCount(event.rules);
        for (const rule of event.new_rules ?? []) {
          if (event.game_index === undefined) continue;
          pushActivity({
            kind: 'analysis', game: event.game_index, tag: 'new rule discovered',
            text: `${rule.rule}: ${rule.outcome === 'safe' ? 'always safe' : 'always a mine'} in all ${rule.seen} cases seen so far.`,
          });
        }
        for (const m of event.mistakes ?? []) {
          if (event.game_index === undefined) continue;
          const risk = m.estimated_risk;
          pushActivity(m.agent === 'memory' ? {
            kind: 'lesson', game: event.game_index, tag: 'learned from its mistake',
            text: `Learning agent hit a mine it rated ${risk !== undefined ? pct(risk) : '?'} risky; that situation is now marked more dangerous.`,
          } : {
            kind: 'lesson', game: event.game_index, tag: 'shared mistake saved',
            text: `No-learning agent hit a mine (${m.message}). Saved to memory for the learning agent; the no-learning agent itself won't use it.`,
          });
        }
        refreshMemory();
        break;
      case 'lessons_updated':
        setLessons(event.lessons);
        if (event.analysis) pushActivity({ kind: 'analysis', game: event.game_index, tag: 'reflection', text: event.analysis });
        if (event.changes.length) {
          setRecentChanges(Object.fromEntries(event.changes.map((c) => [c.id, c.type])));
          for (const change of event.changes) {
            pushActivity({ kind: 'lesson', game: event.game_index, tag: change.type, text: `L${change.id}: ${change.text}` });
          }
        }
        break;
      case 'runner_restarted':
        pushActivity({
          kind: 'error', tag: 'auto-restart',
          text: `The run stopped unexpectedly (${event.reason}). It continues from the next unfinished board in ${event.delay}s (automatic restart ${event.attempt}).`,
        });
        break;
      case 'agent_error':
        pushActivity({ kind: 'error', game: event.game_index, tag: `${AGENT_META[event.agent].short}: error`, text: event.error });
        break;
      default:
        break;
    }
  }, [load, pushActivity, refreshMemory]);

  useEffect(() => {
    if (!experimentId) return;
    const socket = new ExperimentSocket(experimentId, handleEvent, setConnected);
    socket.open();
    return () => socket.close();
  }, [experimentId, handleEvent]);

  // When the live connection comes back after a drop (e.g. the server restarted and resumed the run),
  // reload so the page shows the current state instead of the frozen boards from before.
  const wasConnected = useRef<boolean | null>(null);
  useEffect(() => {
    if (connected && wasConnected.current === false) load();
    wasConnected.current = connected;
  }, [connected, load]);

  // Cross-check with the server every 30 s while a run is active: if the server is further along than
  // this page (or its status changed), reload. The page can never stay frozen on stale data.
  const localPlayed = useRef(0);
  useEffect(() => {
    if (!experiment?.is_active) return;
    const timer = window.setInterval(async () => {
      try {
        const fresh = await api.getExperiment(experimentId);
        const served = fresh.summary?.memory?.games_played ?? 0;
        if (fresh.status !== experiment.status || served > localPlayed.current + 2) load();
      } catch {
        /* next tick retries */
      }
    }, 30000);
    return () => window.clearInterval(timer);
  }, [experiment?.is_active, experiment?.status, experimentId, load]);

  // Backup refresh if the live connection drops while a run is active.
  useEffect(() => {
    if (connected || !experiment?.is_active) return;
    const timer = window.setInterval(load, 15000);
    return () => window.clearInterval(timer);
  }, [connected, experiment?.is_active, load]);

  const split = useMemo(() => ({
    memory: games.filter((g) => g.agent === 'memory'),
    baseline: games.filter((g) => g.agent === 'baseline'),
    expert: games.filter((g) => g.agent === 'expert'),
  }), [games]);
  const summaries = useMemo(() => ({
    memory: summarize(split.memory), baseline: summarize(split.baseline), expert: summarize(split.expert),
  }), [split]);
  localPlayed.current = summaries.memory.games_played;
  const length = experiment?.num_games ?? 0;
  const played = Math.max(summaries.memory.games_played, summaries.baseline.games_played);
  const smoothing = Math.max(5, Math.min(50, Math.round(played / 10) || 5));
  const chartLength = Math.max(1, played);

  const winSeries = useMemo<Series[]>(() => {
    const series: Series[] = AGENTS.map((agent) => ({
      key: agent,
      label: AGENT_META[agent].short,
      color: AGENT_META[agent].color,
      values: rollingWinRate(split[agent], chartLength, smoothing),
    }));
    if (split.expert.length) {
      series.push({ key: 'expert', label: EXPERT_META.short, color: EXPERT_META.color, reference: true,
                    values: rollingWinRate(split.expert, chartLength, smoothing) });
    }
    return series;
  }, [split, chartLength, smoothing]);

  const movesSeries = useMemo<Series[]>(() => {
    const byIndex = new Map(games.map((g) => [g.game_index, g.min_clicks]));
    const minimum = Array.from({ length: chartLength }, (_, i) => byIndex.get(i) ?? null);
    return [
      ...AGENTS.map((agent) => ({
        key: agent,
        label: AGENT_META[agent].short,
        color: AGENT_META[agent].color,
        values: rollingMean(movesWhenWon(split[agent], chartLength), smoothing),
      })),
      { key: 'minimum', label: 'Minimum', color: '#94a3b8', reference: true, values: rollingMean(minimum, smoothing) },
    ];
  }, [split, games, chartLength, smoothing]);

  const control = async (action: 'pause' | 'resume' | 'stop') => {
    if (!experiment) return;
    setBusy(true);
    try {
      await api.control(experiment.id, action);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const changeSpeed = async (speed: 'watch' | 'fast') => {
    if (!experiment) return;
    try {
      await api.setSpeed(experiment.id, speed);
      setExperiment({ ...experiment, speed });
    } catch (e: any) {
      setError(e.message);
    }
  };

  const remove = async () => {
    if (!experiment) return;
    const keeps = isCodeOnly
      ? (experiment.memory_scope === 'persistent' ? 'The persistent memory keeps what it learned.' : 'Its fresh memory is deleted too.')
      : 'Lessons it produced stay in the playbook.';
    if (!window.confirm(`Delete this experiment and all its games? ${keeps}`)) return;
    try {
      await api.deleteExperiment(experiment.id);
      navigate('/');
    } catch (e: any) {
      setError(e.message);
    }
  };

  if (!experiment) {
    return (
      <div className="text-sm text-slate-400">
        {error ? <p className="text-red-300">{error}</p> : 'Loading experiment…'}
      </div>
    );
  }

  const { memory: mem, baseline } = summaries;
  const diff = mem.win_rate !== null && baseline.win_rate !== null ? mem.win_rate - baseline.win_rate : null;
  const progress = length ? (mem.games_played + baseline.games_played) / (2 * length) : 0;
  const canResume = ['paused', 'interrupted', 'stopped', 'failed', 'created'].includes(experiment.status);

  return (
    <div className="mx-auto max-w-[1600px] space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link to="/" className="meta hover:text-slate-200">← All experiments</Link>
          <h1 className="mt-1 text-2xl font-semibold text-slate-100">{experiment.name}</h1>
          <p className="meta num mt-1">
            {experiment.rows}×{experiment.cols} board, {experiment.mines} mines · {experiment.num_games} games per agent ·
            {isCodeOnly ? ' code-only agents (no LLM)' : <> model <code>{modelLabel(experiment.model)}</code></>} ·
            seed {experiment.base_seed} · memory {experiment.memory_scope}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={STATUS_BADGE[experiment.status] ?? 'badge-neutral'}>{experiment.status}</span>
          {experiment.is_active && (
            <span className={connected ? 'badge-emerald' : 'badge-amber'}>{connected ? 'live' : 'reconnecting'}</span>
          )}
          {isCodeOnly && (
            <div role="group" aria-label="Speed" className="flex overflow-hidden rounded-lg border border-slate-600">
              {(['watch', 'fast'] as const).map((s) => (
                <button key={s} type="button" aria-pressed={experiment.speed === s} onClick={() => changeSpeed(s)}
                        className={`px-3 py-1.5 text-sm font-medium ${experiment.speed === s ? 'bg-slate-600 text-white' : 'text-slate-300 hover:bg-slate-700'}`}>
                  {s === 'watch' ? 'Watch' : 'Fast'}
                </button>
              ))}
            </div>
          )}
          {experiment.status === 'running' && (
            <button type="button" className="btn-warn" disabled={busy} onClick={() => control('pause')}>Pause</button>
          )}
          {canResume && experiment.status !== 'completed' && (
            <button type="button" className="btn-primary" disabled={busy} onClick={() => control('resume')}>
              {experiment.status === 'paused' ? 'Resume' : 'Continue'}
            </button>
          )}
          {experiment.is_active && (
            <button type="button" className="btn-secondary" disabled={busy} onClick={() => control('stop')}>Stop</button>
          )}
          {!experiment.is_active && (
            <button type="button" className="btn-ghost text-red-300" onClick={remove}>Delete</button>
          )}
        </div>
      </div>

      {(error || experiment.error) && (
        <div role="alert" className="rounded-lg border border-red-700/60 bg-red-950 px-4 py-3 text-sm text-red-200">
          {error || experiment.error}
        </div>
      )}

      <section aria-label="Headline comparison" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="card p-4">
          <div className="meta">Win rate: learning vs no learning</div>
          <div className="num mt-1 text-2xl font-semibold text-slate-100">
            {pct(mem.win_rate)} <span className="text-base font-normal text-slate-400">vs</span> {pct(baseline.win_rate)}
          </div>
          <div className="meta num mt-1">
            {diff === null ? 'Waiting for finished games' : `${diff >= 0 ? '+' : ''}${(diff * 100).toFixed(1)} points for the learning agent`}
          </div>
        </div>
        <div className="card p-4">
          <div className="meta">Last 20 games</div>
          <div className="num mt-1 text-2xl font-semibold text-slate-100">
            {pct(mem.recent_win_rate)} <span className="text-base font-normal text-slate-400">vs</span> {pct(baseline.recent_win_rate)}
          </div>
          <div className="meta num mt-1">
            {summaries.expert.games_played ? `Expert rules reference: ${pct(summaries.expert.win_rate)}` : 'Recent form shows the trend'}
          </div>
        </div>
        <div className="card p-4">
          <div className="meta">Iterations (moves played)</div>
          <div className="num mt-1 text-2xl font-semibold text-slate-100">{compact(mem.total_moves + baseline.total_moves)}</div>
          <div className="meta num mt-1">
            {mem.games_played + baseline.games_played} of {2 * length} games · {pct(progress)}
          </div>
        </div>
        <div className="card p-4">
          {isCodeOnly ? (
            <>
              <div className="meta">Learning agent's memory</div>
              <div className="num mt-1 text-2xl font-semibold text-slate-100">
                {compact(rulesCount ?? memory?.rules_discovered ?? 0)} rules
                <span className="text-base font-normal text-slate-400"> · {compact(memoryCount?.patterns ?? ((memory?.patterns_3x3 ?? 0) + (memory?.patterns_5x5 ?? 0)))} situations</span>
              </div>
              <div className="meta num mt-1">
                {learnedFrom
                  ? `this run: ${compact(learnedFrom.memory)} from its own games, ${compact(learnedFrom.baseline)} from the no-learning agent's`
                  : `from ${compact(memoryCount?.observations ?? memory?.observations ?? 0)} observed cells · no LLM used`}
              </div>
            </>
          ) : (
            <>
              <div className="meta">LLM usage</div>
              <div className="num mt-1 text-2xl font-semibold text-slate-100">{compact(mem.llm_calls + baseline.llm_calls)} calls</div>
              <div className="meta num mt-1">{compact(mem.tokens)} tokens memory · {compact(baseline.tokens)} baseline</div>
            </>
          )}
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        {AGENTS.map((agent) => (
          <AgentPanel key={agent} agent={agent} live={live[agent]} summary={summaries[agent]} numGames={length}
                      agentType={experiment.agent_type} />
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <LineChart
          title={`Win rate over games (rolling ${smoothing})`}
          description="Share of recent games won. Both reason from the numbers; the blue line pulls ahead as memory discovers rules."
          series={winSeries}
          yDomain={[0, 1]}
          yFormat={(v) => `${Math.round(v * 100)}%`}
        />
        <LineChart
          title={`Moves needed to win (rolling ${smoothing})`}
          description="Moves used in won games, against the board's minimum. Closer to the dashed line is better."
          series={movesSeries}
          yFormat={(v) => num(v, 1)}
        />
      </div>

      {isCodeOnly ? (
        <section className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <LearnedPatterns summary={memory} scope={experiment.memory_scope} liveCount={memoryCount} />
          <ActivityFeed items={activity} empty="Mine hits and what the learning agent takes from them stream in here." />
        </section>
      ) : (
        <PlaybookPanel lessons={lessons} recentChanges={recentChanges} activity={activity} scope={experiment.memory_scope} />
      )}

      <GameLog games={games} onReplay={setReplay} />

      <ReplayDialog experimentId={experiment.id} game={replay} onClose={() => setReplay(null)} />
    </div>
  );
}
