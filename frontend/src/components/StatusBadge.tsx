import React from 'react';

const TONES: Record<string, { className: string; dot: string; label: string }> = {
  created: { className: 'badge-neutral', dot: 'bg-slate-400', label: 'Created' },
  queued: { className: 'badge-neutral', dot: 'bg-slate-400', label: 'Queued' },
  running: { className: 'badge-emerald', dot: 'bg-emerald-400', label: 'Running' },
  paused: { className: 'badge-amber', dot: 'bg-amber-400', label: 'Paused' },
  completed: { className: 'badge-blue', dot: 'bg-blue-400', label: 'Completed' },
  failed: { className: 'badge-red', dot: 'bg-red-400', label: 'Failed' },
  stopped: { className: 'badge-rose', dot: 'bg-rose-400', label: 'Stopped' }
};

const StatusBadge = ({ status }: { status: string }) => {
  const tone = TONES[(status || '').toLowerCase()] || TONES.created;
  return (
    <span className={tone.className}>
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
      {tone.label}
    </span>
  );
};

export default StatusBadge;
