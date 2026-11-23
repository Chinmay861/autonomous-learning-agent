/**
 * Backend URL resolution.
 *
 * Local development: leave VITE_* unset. Requests stay relative ("/api", "/ws") and
 * Vite's dev proxy forwards them to http://localhost:8000.
 *
 * Hosted (Render static site): set VITE_API_BASE_URL (and optionally VITE_WS_BASE_URL)
 * to the backend URL. A missing scheme is treated as https.
 */
function normalize(raw?: string): string {
  const value = (raw || '').trim();
  if (!value) return '';
  const withScheme = /^https?:\/\//i.test(value) ? value : `https://${value}`;
  return withScheme.replace(/\/$/, '').replace(/\/api$/i, '');
}

const backendBase = normalize(import.meta.env.VITE_API_BASE_URL);
const wsBase = normalize(import.meta.env.VITE_WS_BASE_URL) || backendBase;

export const API_BASE = backendBase ? `${backendBase}/api` : '/api';
export const WS_BASE = wsBase ? wsBase.replace(/^http/i, 'ws') : '';

export function experimentSocketUrl(experimentId: string, token: string): string {
  const path = `/ws/experiments/${experimentId}?token=${encodeURIComponent(token)}`;
  if (WS_BASE) return `${WS_BASE}${path}`;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}
