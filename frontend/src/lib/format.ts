export const pct = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined ? '–' : `${(value * 100).toFixed(digits)}%`;

export const num = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined ? '–' : value.toFixed(digits).replace(/\.0+$/, '');

export const compact = (value: number) =>
  new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);

const PROVIDER_NAMES: Record<string, string> = {
  groq: 'Groq', ollama: 'Ollama', openai: 'OpenAI', gemini: 'Gemini', openrouter: 'OpenRouter', custom: 'Custom',
};

/** "groq:openai/gpt-oss-20b" -> "openai/gpt-oss-20b (Groq)". Unprefixed names are shown as-is. */
export function modelLabel(model: string): string {
  const i = model.indexOf(':');
  const provider = i > 0 ? model.slice(0, i).toLowerCase() : '';
  if (!PROVIDER_NAMES[provider]) return model;
  return `${model.slice(i + 1)} (${PROVIDER_NAMES[provider]})`;
}

export const STATUS_BADGE: Record<string, string> = {
  created: 'badge-neutral',
  running: 'badge-emerald',
  paused: 'badge-amber',
  completed: 'badge-blue',
  stopped: 'badge-neutral',
  failed: 'badge-red',
  interrupted: 'badge-amber',
  won: 'badge-emerald',
  lost: 'badge-red',
  timeout: 'badge-amber',
  playing: 'badge-purple',
};
