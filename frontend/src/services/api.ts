import type {
  Experiment, ExperimentCreate, GameRecord, Lesson, MemorySummary, Options, ReplayMove, User,
} from '../types';
import { API_BASE } from './backendUrl';

class ApiClient {
  private async request<T>(url: string, options: RequestInit = {}): Promise<T> {
    const token = localStorage.getItem('token');
    const headers = new Headers(options.headers || {});
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    // Abort slow requests (e.g. a cold backend) instead of hanging forever.
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(`${API_BASE}${url}`, { ...options, headers, signal: controller.signal });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const detail = Array.isArray(data.detail)
          ? data.detail.map((d: { msg?: string }) => d.msg).join('; ')
          : data.detail;
        throw new Error(detail || `Request failed (${response.status}).`);
      }
      return response.json();
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        throw new Error('The request timed out. The backend may be waking up: wait a moment and try again.');
      }
      throw err;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  // Auth
  async login(formData: FormData): Promise<{ access_token: string }> {
    const response = await fetch(`${API_BASE}/auth/login`, { method: 'POST', body: formData });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || 'Unable to sign in. Check your username and password.');
    }
    return response.json();
  }

  register(data: { username: string; email: string; password: string }) {
    return this.request('/auth/register', { method: 'POST', body: JSON.stringify(data) });
  }

  getMe() {
    return this.request<User>('/auth/me');
  }

  // Experiments
  getOptions() {
    return this.request<Options>('/options');
  }

  listExperiments() {
    return this.request<Experiment[]>('/experiments');
  }

  getExperiment(id: string) {
    return this.request<Experiment>(`/experiments/${id}`);
  }

  createExperiment(body: ExperimentCreate) {
    return this.request<Experiment>('/experiments', { method: 'POST', body: JSON.stringify(body) });
  }

  control(id: string, action: 'start' | 'pause' | 'resume' | 'stop') {
    return this.request<{ status: string }>(`/experiments/${id}/${action}`, { method: 'POST' });
  }

  deleteExperiment(id: string) {
    return this.request(`/experiments/${id}`, { method: 'DELETE' });
  }

  listGames(id: string) {
    return this.request<GameRecord[]>(`/experiments/${id}/games`);
  }

  getMoves(id: string, gameId: number) {
    return this.request<{ game: GameRecord; opening_grid: string[]; moves: ReplayMove[] }>(`/experiments/${id}/games/${gameId}/moves`);
  }

  setSpeed(id: string, speed: 'watch' | 'fast') {
    return this.request<{ speed: string }>(`/experiments/${id}/speed`, { method: 'POST', body: JSON.stringify({ speed }) });
  }

  getExperimentMemory(id: string) {
    return this.request<MemorySummary>(`/experiments/${id}/memory`);
  }

  // Persistent pattern memory (code-only agents)
  getMemory() {
    return this.request<MemorySummary>('/memory');
  }

  resetMemory() {
    return this.request<{ deleted_patterns: number }>('/memory/reset', { method: 'POST' });
  }

  // Playbook (LLM agents)
  listLessons(includeRetired = false) {
    return this.request<Lesson[]>(`/lessons${includeRetired ? '?include_retired=true' : ''}`);
  }

  retireLesson(id: number) {
    return this.request<Lesson>(`/lessons/${id}`, { method: 'DELETE' });
  }

  resetPlaybook() {
    return this.request<{ retired: number }>('/lessons/reset', { method: 'POST' });
  }
}

export const api = new ApiClient();
