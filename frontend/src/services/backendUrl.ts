/**
 * Backend URL resolution.
 *
 * Local development: leave the VITE_* variables unset — requests stay relative
 * ("/api", "/ws") and Vite's dev proxy forwards them to http://localhost:8000.
 *
 * Hosted (Render static site): set VITE_API_BASE_URL (and optionally
 * VITE_WS_BASE_URL) to the backend service URL. A missing scheme is treated as
 * https so Render's `fromService` host value works as-is.
 */

function normalize(raw?: string): string {
  const value = (raw || '').trim();
  if (!value) return '';
  const withScheme = /^https?:\/\//i.test(value) ? value : `https://${value}`;
  return withScheme.replace(/\/$/, '').replace(/\/api$/i, '');
}

const backendBase = normalize(import.meta.env.VITE_API_BASE_URL);
const wsBase = normalize(import.meta.env.VITE_WS_BASE_URL) || backendBase;

/** REST base, e.g. "/api" locally or "https://backend.onrender.com/api" when hosted. */
export const API_BASE = backendBase ? `${backendBase}/api` : '/api';

/** WebSocket base (empty = same origin), e.g. "wss://backend.onrender.com". */
export const WS_BASE = wsBase ? wsBase.replace(/^http/i, 'ws') : '';

export function websocketUrl(taskId: string, token: string): string {
  if (WS_BASE) {
    return `${WS_BASE}/ws/${taskId}?token=${encodeURIComponent(token)}`;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/${taskId}?token=${encodeURIComponent(token)}`;
}
