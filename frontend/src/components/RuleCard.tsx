import React from 'react';
import { Rule } from '../types';
import ConfidenceBar from './ConfidenceBar';

const STATUS_TONES: Record<string, { className: string; label: string }> = {
  active: { className: 'badge-emerald', label: 'Active' },
  verified: { className: 'badge-blue', label: 'Verified' },
  abandoned: { className: 'badge-red', label: 'Abandoned' }
};

const RuleCard = ({ rule }: { rule: Rule }) => {
  const tone = STATUS_TONES[rule.status] || { className: 'badge-neutral', label: rule.status };

  return (
    <article className="card flex h-full flex-col justify-between p-4">
      <div>
        <div className="mb-3 flex items-start justify-between gap-3">
          <span className={tone.className}>{tone.label}</span>
          <span className="num text-xs text-slate-400">
            {rule.evidence_count} evidence {rule.evidence_count === 1 ? 'item' : 'items'}
          </span>
        </div>
        <p className="mb-4 text-sm leading-relaxed text-slate-200">{rule.content}</p>
      </div>

      <div className="mt-auto">
        <div className="mb-1 text-xs text-slate-400">Confidence</div>
        <ConfidenceBar confidence={rule.confidence} label="Rule confidence" />
      </div>
    </article>
  );
};

export default RuleCard;
