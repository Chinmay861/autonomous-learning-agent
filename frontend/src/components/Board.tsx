import { memo } from 'react';
import type { CellAction } from '../types';

const NUMBER_INK: Record<string, string> = {
  '1': 'text-sky-300',
  '2': 'text-emerald-300',
  '3': 'text-rose-300',
  '4': 'text-violet-300',
  '5': 'text-amber-300',
  '6': 'text-cyan-300',
  '7': 'text-slate-100',
  '8': 'text-slate-300',
};

function describe(symbol: string): string {
  switch (symbol) {
    case '#': return 'hidden';
    case 'F': return 'flagged';
    case '.': return 'empty';
    case '*': return 'mine';
    case 'X': return 'exploded mine';
    default: return `${symbol} adjacent mines`;
  }
}

interface BoardProps {
  grid: string[];
  /** The most recent action, outlined in the agent's color. */
  highlight?: CellAction | null;
  accent?: string;
  label: string;
}

/**
 * Renders a Minesweeper grid from the engine's symbol rows:
 * `#` hidden, `F` flag, `.` empty, `1`-`8` counts, `*` mine, `X` exploded mine.
 */
function BoardView({ grid, highlight, accent = '#6ee7b7', label }: BoardProps) {
  const rows = grid.length;
  const cols = rows ? grid[0].length : 0;
  const dense = cols > 12;

  return (
    <div
      role="img"
      aria-label={label}
      className="grid w-full select-none gap-px rounded-lg bg-slate-950 p-1"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {grid.flatMap((row, r) =>
        row.split('').map((symbol, c) => {
          const isLast = highlight && highlight.row === r && highlight.col === c;
          let cls = 'flex aspect-square items-center justify-center rounded-[3px] font-bold leading-none ';
          cls += dense ? 'text-[9px] sm:text-[10px] ' : 'text-[11px] sm:text-sm ';
          let content: string = '';
          if (symbol === '#') {
            cls += 'bg-slate-600 shadow-[inset_0_-2px_0_rgba(0,0,0,0.25)]';
          } else if (symbol === 'F') {
            cls += 'bg-slate-600 text-amber-300';
            content = '⚑';
          } else if (symbol === '*') {
            cls += 'bg-slate-700 text-slate-200';
            content = '●';
          } else if (symbol === 'X') {
            cls += 'bg-red-700 text-white';
            content = '●';
          } else {
            cls += `bg-slate-800 ${NUMBER_INK[symbol] ?? 'text-slate-500'}`;
            content = symbol === '.' ? '' : symbol;
          }
          return (
            <div
              key={`${r}-${c}`}
              title={`(${r},${c}) ${describe(symbol)}`}
              className={cls}
              style={isLast ? { outline: `2px solid ${accent}`, outlineOffset: '-2px' } : undefined}
            >
              {content}
            </div>
          );
        }),
      )}
    </div>
  );
}

export const Board = memo(BoardView);
