import React from 'react';

const ConfidenceBar = ({
  confidence,
  label = 'Confidence'
}: {
  confidence: number;
  label?: string;
}) => {
  // Confidence arrives as 0.0 - 1.0
  const percentage = Math.round(Math.min(1, Math.max(0, confidence)) * 100);

  let fill = 'bg-red-400';
  if (percentage >= 80) fill = 'bg-emerald-400';
  else if (percentage >= 50) fill = 'bg-amber-400';

  return (
    <div className="flex items-center gap-2">
      <div
        role="meter"
        aria-label={label}
        aria-valuenow={percentage}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={`${percentage}%`}
        className="h-1.5 min-w-[50px] flex-1 overflow-hidden rounded-full bg-slate-700"
      >
        <div
          aria-hidden="true"
          className={`h-full rounded-full ${fill} transition-[width] duration-300 motion-reduce:transition-none`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="num w-9 text-right text-xs text-slate-400">{percentage}%</span>
    </div>
  );
};

export default ConfidenceBar;
