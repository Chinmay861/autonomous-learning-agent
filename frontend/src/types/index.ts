export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
}

export interface Task {
  id: string;
  title: string;
  description: string;
  status: 'created' | 'running' | 'paused' | 'completed' | 'failed' | 'stopped' | string;
  max_iterations: number;
  snapshot_interval: number;
  synthesis_interval: number;
  model: string;
  temperature: number;
  persistent_learning: boolean;
  use_persistent_learning?: boolean;
  current_iteration?: number;
  created_at: string;
  updated_at: string;
}

export interface TaskCreate {
  title: string;
  description: string;
  max_iterations?: number;
  snapshot_interval?: number;
  synthesis_interval?: number;
  model?: string;
  temperature?: number;
  persistent_learning?: boolean;
  use_persistent_learning?: boolean;
}

export interface Iteration {
  id: string;
  task_id: string;
  iteration_number: number;
  observation: string;
  hypothesis: string;
  action: string;
  result: string;
  evaluation: string;
  created_at: string;
}

export interface Rule {
  id: string;
  task_id: string;
  content: string;
  status: 'active' | 'abandoned' | 'verified';
  confidence: number;
  evidence_count: number;
  last_updated: string;
}

export interface LearningRecord {
  id: string;
  task_id: string;
  content: string;
  category: string;
  iteration_number: number;
  created_at: string;
}

export interface Snapshot {
  id: string;
  task_id: string;
  iteration_number: number;
  data: any;
  created_at: string;
}

export interface Strategy {
  id: string;
  task_id: string;
  content: string;
  status: 'active' | 'abandoned';
  created_at: string;
}

export interface MemorySearchResult {
  id: string;
  content: string;
  metadata: any;
  score: number;
}

export interface MemoryStats {
  total_memories: number;
  global_count: number;
  task_count: number;
  avg_confidence: number;
  recent_additions: number;
}

export interface Settings {
  default_model: string;
  default_max_iterations: number;
  default_snapshot_interval: number;
  default_synthesis_interval: number;
  persistent_learning_enabled: boolean;
  tool_permissions: string;
  llm_provider?: string;
  cloud_model?: string;
  cloud_base_url?: string;
  has_groq_key?: boolean;
  has_gemini_key?: boolean;
  has_openai_key?: boolean;
  has_openrouter_key?: boolean;
}

export interface HardwareInfo {
  cpu_info: string;
  ram_total: string;
  gpu_info?: string;
}

export interface AgentEvent {
  type: 'iteration_start' | 'iteration_complete' | 'rule_updated' | 'strategy_changed' | 'learning_recorded' | 'status_changed';
  data: any;
}
