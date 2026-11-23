import { useEffect, useRef, useState } from 'react';
import type { AgentKind, GameRecord, ReplayMove } from '../types';
import { api } from '../services/api';
import { AGENT_META } from '../lib/agents';
import { STATUS_BADGE } from '../lib/format';
import { Board } from './Board';

interface ReplayDialogProps {
  experimentId: string;
  game: GameRecord | null;
  onClose: () => void;
}

/** Step through every move of a finished game with the agent's reasoning. */
export function ReplayDialog({ experimentId, game, onClose }: ReplayDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [moves, setMoves] = useState<ReplayMove[]>([]);
  const [opening, setOpening] = useState<string[]>([]);
  const [step, setStep] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (game && !dialog.open) dialog.showModal();
    if (!game && dialog.open) dialog.close();
  }, [game]);

  useEffect(() => {
    if (!game) return;
    setMoves([]);
    setError('');
    api.getMoves(experimentId, game.id)
      .then((data) => {
        setMoves(data.moves);
        setOpening(data.opening_grid);
        setStep(data.moves.length);
      })
      .catch((e) => setError(e.message));
  }, [experimentId, game]);

  if (!game) return <dialog ref={dialogRef} onClose={onClose} />;

  const meta = AGENT_META[game.agent as AgentKind];
  const current = step > 0 ? moves[step - 1] : null;
  // Final step shows the mines; step 0 is the opening the agent started from.
  const grid = step >= moves.length && game.final_grid.length ? game.final_grid
    : current ? current.grid_after
      : opening.length ? opening : game.final_grid;

  return (
    <dialog ref={dialogRef} onClose={onClose}
            className="w-[min(100vw-2rem,56rem)] rounded-xl border border-slate-600 bg-slate-800 p-0 text-slate-100 backdrop:bg-black/60">
      <div className="flex items-start justify-between gap-3 border-b border-slate-700 px-5 py-4">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <svg width="18" height="8" aria-hidden="true"><line x1="0" y1="4" x2="18" y2="4" stroke={meta.color} strokeWidth="3" /></svg>
            {meta.label}: game {game.game_index + 1}
          </h2>
          <p className="meta num mt-1">
            <span className={STATUS_BADGE[game.status]}>{game.status}</span>{' '}
            {game.moves} moves (minimum {game.min_clicks}) · {game.invalid_moves} invalid · seed {game.seed}
          </p>
        </div>
        <button type="button" className="btn-ghost" onClick={onClose}>Close</button>
      </div>

      <div className="grid gap-5 p-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div>
          <Board grid={grid} highlight={current?.action ?? null} accent={meta.color}
                 label={`Replay of game ${game.game_index + 1}, after move ${step}`} />
          {moves.length > 0 && (
            <div className="mt-3">
              <label htmlFor="replay-step" className="label num">Move {step} of {moves.length}</label>
              <input id="replay-step" type="range" min={0} max={moves.length} value={step}
                     onChange={(e) => setStep(Number(e.target.value))} className="w-full accent-emerald-400" />
              <div className="mt-2 flex gap-2">
                <button type="button" className="btn-secondary px-3 py-1" disabled={step === 0} onClick={() => setStep(step - 1)}>Previous</button>
                <button type="button" className="btn-secondary px-3 py-1" disabled={step >= moves.length} onClick={() => setStep(step + 1)}>Next</button>
              </div>
            </div>
          )}
        </div>

        <div className="min-w-0">
          {error && <p className="text-sm text-red-300">{error}</p>}
          {current ? (
            <div className="mb-4 rounded-lg border border-slate-700 bg-slate-900/50 p-3">
              <div className="flex items-center gap-2">
                <code className="text-sm font-semibold">
                  {current.action ? `${current.action.action}(${current.action.row},${current.action.col})` : 'unparseable'}
                </code>
                <span className={current.valid ? (current.outcome === 'mine' ? 'badge-red' : 'badge-emerald') : 'badge-rose'}>
                  {current.outcome}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-300">{current.message}</p>
              {current.reasoning && <p className="mt-2 text-xs italic text-slate-400">“{current.reasoning}”</p>}
            </div>
          ) : (
            <p className="mb-4 text-sm text-slate-400">The opening position, before the first move.</p>
          )}

          {game.mistakes.length > 0 && (
            <>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Mistakes in this game</h3>
              <ul className="space-y-1.5 text-xs">
                {game.mistakes.map((m) => (
                  <li key={m.move}>
                    <button type="button" className="text-left hover:underline" onClick={() => setStep(m.move + 1)}>
                      <span className="num text-slate-400">Move {m.move + 1}: </span>
                      <span className="text-rose-300">{m.type.replace(/_/g, ' ')}</span>
                      <span className="text-slate-300">: {m.message}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}
