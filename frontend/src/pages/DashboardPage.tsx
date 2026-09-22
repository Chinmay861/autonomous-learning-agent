import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import { Task, MemoryStats } from '../types';
import StatusBadge from '../components/StatusBadge';

const DashboardPage = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [formError, setFormError] = useState('');
  const [creating, setCreating] = useState(false);

  const [formData, setFormData] = useState({
    title: '',
    description: '',
    max_iterations: 100,
    snapshot_interval: 10,
    synthesis_interval: 5,
    model: '',
    temperature: 0.7,
    persistent_learning: true
  });

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [fetchedTasks, fetchedStats, fetchedModels, fetchedSettings] = await Promise.all([
        api.getTasks(),
        api.getMemoryStats().catch(() => null),
        api.listModels().catch(() => []),
        api.getSettings().catch(() => null),
      ]);
      const modelList = Array.isArray(fetchedModels) && fetchedModels.length > 0 ? fetchedModels : ['phi3:mini'];
      setTasks(Array.isArray(fetchedTasks) ? fetchedTasks : []);
      setStats(fetchedStats);
      setModels(modelList);
      setFormData(prev => ({
        ...prev,
        model: prev.model || (fetchedSettings?.default_model || modelList[0]),
        persistent_learning: fetchedSettings?.persistent_learning_enabled !== undefined ? fetchedSettings.persistent_learning_enabled : prev.persistent_learning,
        max_iterations: fetchedSettings?.default_max_iterations || prev.max_iterations,
        snapshot_interval: fetchedSettings?.default_snapshot_interval || prev.snapshot_interval,
        synthesis_interval: fetchedSettings?.default_synthesis_interval || prev.synthesis_interval,
      }));
    } catch (error: any) {
      setLoadError(error?.message || 'Unable to load your tasks. Check the connection and try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    setCreating(true);
    try {
      await api.createTask({
        ...formData,
        use_persistent_learning: formData.persistent_learning
      });
      setShowForm(false);
      setFormData(prev => ({ ...prev, title: '', description: '' }));
      await fetchData();
    } catch (error: any) {
      setFormError(error?.message || 'Unable to create the task. Check the details and try again.');
    } finally {
      setCreating(false);
    }
  };

  const activeTasks = tasks.filter(t => t.status === 'running').length;

  if (loading) {
    return (
      <div role="status" className="py-16 text-center text-sm text-slate-400">
        Loading dashboard…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <button
          type="button"
          onClick={() => setShowForm(!showForm)}
          aria-expanded={showForm}
          className={showForm ? 'btn-secondary' : 'btn-primary'}
        >
          {showForm ? 'Close form' : 'New task'}
        </button>
      </div>

      {loadError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-700/60 bg-red-950 px-4 py-3 text-sm text-red-200">
          <span>{loadError}</span>
          <button type="button" onClick={fetchData} className="btn-secondary px-3 py-1.5 text-xs">
            Try again
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="card p-5">
          <div className="mb-1 text-sm text-slate-400">Total tasks</div>
          <div className="num text-3xl font-bold">{tasks.length}</div>
        </div>
        <div className="card p-5">
          <div className="mb-1 text-sm text-slate-400">Running now</div>
          <div className="num text-3xl font-bold text-emerald-300">{activeTasks}</div>
        </div>
        <div className="card p-5">
          <div className="mb-1 text-sm text-slate-400">Stored memories</div>
          <div className="num text-3xl font-bold text-blue-300">{stats?.total_memories ?? 0}</div>
        </div>
      </div>

      {showForm && (
        <section aria-labelledby="create-task-heading" className="card p-5 sm:p-6">
          <h2 id="create-task-heading" className="mb-4 border-b border-slate-700 pb-2 text-lg font-semibold">
            Create task
          </h2>

          {formError && (
            <div role="alert" className="mb-4 rounded-lg border border-red-700/60 bg-red-950 px-4 py-3 text-sm text-red-200">
              {formError}
            </div>
          )}

          <form onSubmit={handleCreateTask} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="md:col-span-2">
                <label htmlFor="task-title" className="label">
                  Title
                </label>
                <input
                  id="task-title"
                  type="text"
                  required
                  value={formData.title}
                  onChange={e => setFormData({ ...formData, title: e.target.value })}
                  className="input"
                />
              </div>

              <div className="md:col-span-2">
                <label htmlFor="task-description" className="label">
                  Description
                </label>
                <textarea
                  id="task-description"
                  required
                  rows={4}
                  value={formData.description}
                  onChange={e => setFormData({ ...formData, description: e.target.value })}
                  aria-describedby="task-description-hint"
                  className="input"
                />
                <span id="task-description-hint" className="hint">
                  Describe the goal, the rules, and what a successful run looks like.
                </span>
              </div>

              <div>
                <label htmlFor="task-model" className="label">
                  Model
                </label>
                <select
                  id="task-model"
                  value={formData.model}
                  onChange={e => setFormData({ ...formData, model: e.target.value })}
                  className="input"
                >
                  {(models || []).map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="task-temperature" className="label">
                  Temperature
                </label>
                <div className="flex items-center gap-3">
                  <input
                    id="task-temperature"
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    value={formData.temperature}
                    onChange={e => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
                    className="w-full accent-emerald-500"
                  />
                  <output htmlFor="task-temperature" className="num w-8 text-sm text-slate-300">
                    {formData.temperature}
                  </output>
                </div>
              </div>

              <div>
                <label htmlFor="task-max-iterations" className="label">
                  Iteration limit
                </label>
                <input
                  id="task-max-iterations"
                  type="number"
                  min={1}
                  step={1}
                  value={formData.max_iterations}
                  onChange={e => setFormData({ ...formData, max_iterations: parseInt(e.target.value) })}
                  className="input"
                />
              </div>

              <div>
                <label htmlFor="task-snapshot-interval" className="label">
                  Snapshot interval
                </label>
                <input
                  id="task-snapshot-interval"
                  type="number"
                  min={1}
                  step={1}
                  value={formData.snapshot_interval}
                  onChange={e => setFormData({ ...formData, snapshot_interval: parseInt(e.target.value) })}
                  className="input"
                />
              </div>

              <div className="md:col-span-2">
                <label htmlFor="task-persistent-learning" className="flex cursor-pointer select-none items-start gap-3">
                  <input
                    id="task-persistent-learning"
                    type="checkbox"
                    checked={formData.persistent_learning}
                    onChange={e => setFormData({ ...formData, persistent_learning: e.target.checked })}
                    className="mt-0.5 h-4 w-4 rounded border-slate-600 bg-slate-900 text-emerald-600 accent-emerald-600"
                  />
                  <span>
                    <span className="text-sm font-medium text-slate-200">Use stored learnings</span>
                    <span className="hint mt-0.5">
                      Retrieves knowledge from earlier runs when this task executes. New learnings are stored either way.
                    </span>
                  </span>
                </label>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShowForm(false)} className="btn-secondary">
                Cancel
              </button>
              <button type="submit" disabled={creating} className="btn-primary">
                {creating ? 'Creating…' : 'Create task'}
              </button>
            </div>
          </form>
        </section>
      )}

      <section aria-labelledby="recent-tasks-heading" className="card overflow-hidden">
        <h2 id="recent-tasks-heading" className="border-b border-slate-700 p-4 font-semibold">
          Recent tasks
        </h2>

        {tasks.length === 0 ? (
          <div className="p-10 text-center">
            <p className="font-medium text-slate-200">No tasks yet</p>
            <p className="mx-auto mt-1 max-w-sm text-sm text-slate-400">
              A task describes a goal for the agent. It experiments, evaluates results, and stores what it learns.
            </p>
            <button type="button" onClick={() => setShowForm(true)} className="btn-primary mt-5">
              Create your first task
            </button>
          </div>
        ) : (
          <ul className="divide-y divide-slate-700/50">
            {tasks.map(task => (
              <li key={task.id}>
                <Link
                  to={`/tasks/${task.id}`}
                  className="block rounded-sm p-4 transition-colors hover:bg-slate-700/30"
                >
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <h3 className="font-medium text-slate-200">{task.title}</h3>
                    <StatusBadge status={task.status} />
                  </div>
                  <p className="mb-2 line-clamp-2 text-sm text-slate-400">{task.description}</p>
                  <div className="flex flex-wrap items-center gap-4 text-xs text-slate-400">
                    <span>Model: {task.model}</span>
                    <span className="num">
                      Created: <time dateTime={task.created_at}>{new Date(task.created_at).toLocaleDateString()}</time>
                    </span>
                    <span className={(task.persistent_learning ?? task.use_persistent_learning) ? 'badge-emerald' : 'badge-neutral'}>
                      {(task.persistent_learning ?? task.use_persistent_learning) ? 'Learnings: On' : 'Learnings: Off'}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
};

export default DashboardPage;
