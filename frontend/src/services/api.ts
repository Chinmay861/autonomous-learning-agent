import { Task, TaskCreate, Iteration, Rule, LearningRecord, Snapshot, MemorySearchResult, MemoryStats, Settings, HardwareInfo } from '../types';
import { API_BASE } from './backendUrl';

class ApiClient {
  private getToken(): string | null {
    return localStorage.getItem('token');
  }

  private async fetchWithAuth(url: string, options: RequestInit = {}) {
    const token = this.getToken();
    const headers = new Headers(options.headers || {});
    
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    
    // Auto-add Content-Type for JSON if body exists and it's not FormData
    if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(`${API_BASE}${url}`, {
      ...options,
      headers
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || 'Unable to load data. Check your connection and try again.');
    }

    return response.json();
  }

  // Auth
  async login(formData: FormData) {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      body: formData
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || 'Unable to sign in. Check your username and password and try again.');
    }
    return response.json();
  }

  async register(data: any) {
    const response = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || 'Unable to create the account. Check the details and try again.');
    }
    return response.json();
  }

  async getMe() {
    return this.fetchWithAuth('/auth/me');
  }

  // Tasks
  async getTasks(): Promise<Task[]> {
    return this.fetchWithAuth('/tasks');
  }

  async getTask(id: string): Promise<Task> {
    return this.fetchWithAuth(`/tasks/${id}`);
  }

  async createTask(task: TaskCreate): Promise<Task> {
    return this.fetchWithAuth('/tasks', {
      method: 'POST',
      body: JSON.stringify(task)
    });
  }

  async startTask(id: string) {
    return this.fetchWithAuth(`/tasks/${id}/start`, { method: 'POST' });
  }

  async pauseTask(id: string) {
    return this.fetchWithAuth(`/tasks/${id}/pause`, { method: 'POST' });
  }

  async resumeTask(id: string) {
    return this.fetchWithAuth(`/tasks/${id}/resume`, { method: 'POST' });
  }

  async stopTask(id: string) {
    return this.fetchWithAuth(`/tasks/${id}/stop`, { method: 'POST' });
  }

  async updateTask(id: string, updates: Partial<Task>): Promise<Task> {
    return this.fetchWithAuth(`/tasks/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(updates)
    });
  }

  async toggleTaskLearning(id: string, enabled?: boolean): Promise<Task> {
    return this.fetchWithAuth(`/tasks/${id}/toggle-learning`, {
      method: 'POST',
      body: JSON.stringify(enabled !== undefined ? { persistent_learning: enabled, use_persistent_learning: enabled } : {})
    });
  }

  // Iterations
  async getTaskIterations(taskId: string): Promise<Iteration[]> {
    return this.fetchWithAuth(`/tasks/${taskId}/iterations`);
  }

  // Learnings
  async getTaskLearnings(taskId: string): Promise<LearningRecord[]> {
    return this.fetchWithAuth(`/tasks/${taskId}/learnings`);
  }

  async downloadLearnings(taskId: string): Promise<Blob> {
    const token = this.getToken();
    const headers = new Headers();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    
    const response = await fetch(`${API_BASE}/tasks/${taskId}/learnings/download`, { headers });
    if (!response.ok) throw new Error('Unable to download the file. Try again.');
    return response.blob();
  }

  // Rules
  async getTaskRules(taskId: string): Promise<Rule[]> {
    return this.fetchWithAuth(`/tasks/${taskId}/rules`);
  }

  // Snapshots
  async getTaskSnapshots(taskId: string): Promise<Snapshot[]> {
    return this.fetchWithAuth(`/tasks/${taskId}/snapshots`);
  }

  async compareSnapshots(taskId: string, snapshotId1: string, snapshotId2: string) {
    return this.fetchWithAuth(`/tasks/${taskId}/snapshots/compare?id1=${snapshotId1}&id2=${snapshotId2}`);
  }

  // Memory
  async searchMemory(query: string, taskId?: string): Promise<MemorySearchResult[]> {
    const data = await this.fetchWithAuth('/memory/search', {
      method: 'POST',
      body: JSON.stringify({
        query,
        top_k: 20,
        min_similarity: 0.3,
        ...(taskId ? { task_id: taskId } : {})
      })
    });
    return Array.isArray(data) ? data : [];
  }

  async getMemoryStats(): Promise<MemoryStats> {
    return this.fetchWithAuth('/memory/stats');
  }

  // Settings
  async getSettings(): Promise<Settings> {
    return this.fetchWithAuth('/settings');
  }

  async updateSettings(settings: Partial<Settings>): Promise<Settings> {
    return this.fetchWithAuth('/settings', {
      method: 'PUT',
      body: JSON.stringify(settings)
    });
  }

  async listModels(): Promise<string[]> {
    try {
      const data = await this.fetchWithAuth('/settings/models');
      if (Array.isArray(data)) return data;
      if (data && Array.isArray(data.models)) return data.models;
      return [];
    } catch {
      return ['phi3:mini', 'llama3.2:3b'];
    }
  }

  async getHardware(): Promise<HardwareInfo> {
    return this.fetchWithAuth('/settings/hardware');
  }
}

export const api = new ApiClient();
