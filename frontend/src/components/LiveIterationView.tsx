import React, { useEffect, useRef } from 'react';
import { Iteration } from '../types';

const LiveIterationView = ({ iteration, status }: { iteration: Iteration | null; status?: string }) => {
  const containerRef = useRef<HTMLDListElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [iteration]);

  if (!iteration) {
    const isRunning = status?.toLowerCase() === 'running';
    return (
      <div className="flex h-[min(500px,70vh)] flex-col items-center justify-center space-y-4 p-8 text-center">
        {isRunning ? (
          <div role="status" className="flex flex-col items-center space-y-4">
            <div
              aria-hidden="true"
              className="h-10 w-10 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent motion-reduce:animate-none"
            />
            <div className="text-base font-semibold text-emerald-300">Agent is reasoning…</div>
            <div className="max-w-sm text-xs text-slate-400">
              Iteration steps (observation, hypothesis, action, result, evaluation) stream here as they happen.
            </div>
          </div>
        ) : (
          <>
            <div className="text-sm text-slate-400">No iteration is running.</div>
            <div className="text-xs text-slate-400">
              Select Start or Resume above to begin the agent loop.
            </div>
          </>
        )}
      </div>
    );
  }

  const renderSafeContent = (content: any) => {
    if (content === null || content === undefined || content === '') {
      return <span className="italic opacity-60">Pending…</span>;
    }
    if (typeof content === 'object') {
      try {
        return JSON.stringify(content, null, 2);
      } catch {
        return String(content);
      }
    }
    return String(content);
  };

  const formattedTime = (() => {
    try {
      const d = iteration.created_at ? new Date(iteration.created_at) : new Date();
      return isNaN(d.getTime()) ? null : d;
    } catch {
      return null;
    }
  })();

  const sections = [
    { title: 'Observation', content: iteration.observation, color: 'text-blue-300', border: 'border-blue-400/40' },
    { title: 'Hypothesis', content: iteration.hypothesis, color: 'text-amber-300', border: 'border-amber-400/40' },
    { title: 'Action', content: iteration.action, color: 'text-purple-300', border: 'border-purple-400/40' },
    { title: 'Result', content: iteration.result, color: 'text-emerald-300', border: 'border-emerald-400/40' },
    { title: 'Evaluation', content: iteration.evaluation, color: 'text-slate-300', border: 'border-slate-400/40' }
  ];

  return (
    <div className="flex h-[min(600px,70vh)] flex-col rounded-xl border border-slate-700 bg-slate-900">
      <div className="flex items-center justify-between rounded-t-xl border-b border-slate-700 bg-slate-800 p-3">
        <h2 className="num text-sm font-semibold text-emerald-300">
          Iteration #{iteration.iteration_number}
        </h2>
        {formattedTime && (
          <time dateTime={formattedTime.toISOString()} className="num text-xs text-slate-400">
            {formattedTime.toLocaleTimeString()}
          </time>
        )}
      </div>

      <dl ref={containerRef} className="flex-1 space-y-4 overflow-auto p-4 font-mono text-xs">
        {sections.map((section) => (
          <div key={section.title} className={`border-l-2 ${section.border} py-1 pl-4`}>
            <dt className={`mb-1 text-[11px] font-bold uppercase tracking-wider ${section.color}`}>
              {section.title}
            </dt>
            <dd className="whitespace-pre-wrap break-words leading-relaxed text-slate-300">
              {renderSafeContent(section.content)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
};

export default LiveIterationView;
