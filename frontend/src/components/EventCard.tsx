import React from 'react';

interface EventCardProps {
  iterationNumber: number;
  category: string;
  content: string;
  date: string;
}

const CATEGORY_TONES: Record<string, string> = {
  discovery: 'badge-blue',
  mistake: 'badge-red',
  rule: 'badge-emerald',
  strategy: 'badge-purple',
  default: 'badge-neutral'
};

const EventCard = ({ iterationNumber, category, content, date }: EventCardProps) => {
  const tone = CATEGORY_TONES[category?.toLowerCase()] || CATEGORY_TONES.default;

  const timestamp = (() => {
    const d = new Date(date);
    return isNaN(d.getTime()) ? null : d;
  })();

  return (
    <article className="card p-4 transition-colors hover:border-slate-600">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="num text-xs text-slate-400">#{iterationNumber}</span>
          <span className={tone}>{category || 'Event'}</span>
        </div>
        {timestamp && (
          <time dateTime={timestamp.toISOString()} className="num text-xs text-slate-400">
            {timestamp.toLocaleTimeString()}
          </time>
        )}
      </div>
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">{content}</p>
    </article>
  );
};

export default EventCard;
