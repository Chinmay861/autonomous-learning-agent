import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../services/api';
import { wsClient } from '../services/websocket';
import { Task, Iteration, Rule, LearningRecord, Snapshot } from '../types';
import LiveIterationView from '../components/LiveIterationView';
import RuleCard from '../components/RuleCard';
import EventCard from '../components/EventCard';
import StatusBadge from '../components/StatusBadge';
import { ErrorBoundary } from '../components/ErrorBoundary';

const TaskDetailPage = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [activeTab, setActiveTab] = useState('live');
  const [loading, setLoading] = useState(true);
  
  // Tab Data
  const [iterations, setIterations] = useState<Iteration[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [learnings, setLearnings] = useState<LearningRecord[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [currentIteration, setCurrentIteration] = useState<Iteration | null>(null);
  const [actionError, setActionError] = useState('');
  const [busyAction, setBusyAction] = useState('');

  useEffect(() => {
    if (taskId) {
      fetchTaskData();
      
      const token = localStorage.getItem('token');
      if (token) {
        wsClient.connect(taskId, token);
        const unsubscribe = wsClient.onEvent((event: any) => {
          try {
            if (!event) return;
            // Support both nested event.data and flat payload
            const d = (event.data && typeof event.data === 'object') ? event.data : event;

            if (event.type === 'status_changed') {
              const newStatus = d.status || d.completion_status;
              if (newStatus) {
                setTask(prev => prev ? { ...prev, status: newStatus } : prev);
              }
            } else if (event.type === 'iteration_started') {
              const iterNum = d.iteration || d.iteration_number || 1;
              setCurrentIteration({
                id: `${taskId}_${iterNum}`,
                task_id: taskId,
                iteration_number: iterNum,
                observation: 'Observing environment...',
                hypothesis: 'Formulating hypothesis...',
                action: 'Planning action...',
                result: 'Executing...',
                evaluation: 'Pending evaluation...',
                created_at: new Date().toISOString()
              });
            } else if (event.type === 'observation') {
              const obsText = typeof d.state === 'object' ? JSON.stringify(d.state, null, 2) : String(d.state || d.description || '');
              setCurrentIteration(prev => ({
                ...(prev || {
                  id: `${taskId}_active`,
                  task_id: taskId,
                  iteration_number: 1,
                  action: '',
                  result: '',
                  hypothesis: '',
                  evaluation: '',
                  created_at: new Date().toISOString()
                }),
                observation: obsText
              }));
            } else if (event.type === 'hypothesis') {
              const modeText = d.mode ? `[${String(d.mode).toUpperCase()}] ` : '';
              const hypText = typeof d.hypothesis === 'object' ? JSON.stringify(d.hypothesis, null, 2) : String(d.hypothesis || '');
              const reasonText = d.reasoning ? `\n\nReasoning: ${typeof d.reasoning === 'object' ? JSON.stringify(d.reasoning, null, 2) : d.reasoning}` : '';
              setCurrentIteration(prev => ({
                ...(prev || {
                  id: `${taskId}_active`,
                  task_id: taskId,
                  iteration_number: 1,
                  observation: '',
                  action: '',
                  result: '',
                  evaluation: '',
                  created_at: new Date().toISOString()
                }),
                hypothesis: `${modeText}${hypText}${reasonText}`.trim()
              }));
            } else if (event.type === 'action') {
              const actionContent = d.action !== undefined ? d.action : d;
              setCurrentIteration(prev => ({
                ...(prev || {
                  id: `${taskId}_active`,
                  task_id: taskId,
                  iteration_number: 1,
                  observation: '',
                  hypothesis: '',
                  result: '',
                  evaluation: '',
                  created_at: new Date().toISOString()
                }),
                action: typeof actionContent === 'object' ? JSON.stringify(actionContent, null, 2) : String(actionContent || '')
              }));
            } else if (event.type === 'result') {
              const resVal = d.output !== undefined ? d.output : (d.error !== undefined ? d.error : (d.result !== undefined ? d.result : `Reward: ${d.reward ?? 0}`));
              setCurrentIteration(prev => ({
                ...(prev || {
                  id: `${taskId}_active`,
                  task_id: taskId,
                  iteration_number: 1,
                  observation: '',
                  hypothesis: '',
                  action: '',
                  evaluation: '',
                  created_at: new Date().toISOString()
                }),
                result: typeof resVal === 'object' ? JSON.stringify(resVal, null, 2) : String(resVal || '')
              }));
            } else if (event.type === 'evaluation') {
              const evalContent = d.evaluation !== undefined ? d.evaluation : d;
              setCurrentIteration(prev => ({
                ...(prev || {
                  id: `${taskId}_active`,
                  task_id: taskId,
                  iteration_number: 1,
                  observation: '',
                  hypothesis: '',
                  action: '',
                  result: '',
                  created_at: new Date().toISOString()
                }),
                evaluation: typeof evalContent === 'object' ? JSON.stringify(evalContent, null, 2) : String(evalContent || '')
              }));
            } else if (event.type === 'iteration_complete') {
              const iterNum = d.iteration_number || d.iteration || 1;
              const safeIter: Iteration = {
                id: d.id || `${taskId}_${iterNum}`,
                task_id: taskId,
                iteration_number: iterNum,
                action: typeof d.action === 'object' ? JSON.stringify(d.action, null, 2) : String(d.action || ''),
                evaluation: typeof d.evaluation === 'object' ? JSON.stringify(d.evaluation, null, 2) : String(d.evaluation || ''),
                observation: typeof d.observation === 'object' ? JSON.stringify(d.observation, null, 2) : String(d.observation || ''),
                hypothesis: typeof d.hypothesis === 'object' ? JSON.stringify(d.hypothesis, null, 2) : String(d.hypothesis || ''),
                result: typeof d.result === 'object' ? JSON.stringify(d.result, null, 2) : String(d.result || d.action_result || d.output || ''),
                created_at: d.created_at || new Date().toISOString(),
              };
              setCurrentIteration(safeIter);
              setIterations(prev => {
                const exists = prev.some(it => it.iteration_number === safeIter.iteration_number);
                return exists ? prev.map(it => it.iteration_number === safeIter.iteration_number ? safeIter : it) : [...prev, safeIter];
              });
              setTask(prev => prev ? { ...prev, current_iteration: iterNum } : prev);
            } else if (event.type === 'rule_updated') {
              api.getTaskRules(taskId).then(data => Array.isArray(data) && setRules(data)).catch(() => {});
            } else if (event.type === 'learning_created') {
              api.getTaskLearnings(taskId).then(data => Array.isArray(data) && setLearnings(data)).catch(() => {});
            } else if (event.type === 'task_completed') {
              setTask(prev => prev ? { ...prev, status: 'COMPLETED' as any } : prev);
            }
          } catch (err) {
            console.error('Error handling WebSocket event:', err, event);
          }
        });
        
        return () => {
          unsubscribe();
          wsClient.disconnect();
        };
      }
    }
  }, [taskId]);

  const fetchTaskData = async () => {
    if (!taskId) return;
    try {
      const taskData = await api.getTask(taskId);
      setTask(taskData);
      
      // Fetch initial data based on active tab, but let's grab iterations for live view
      const iterData = await api.getTaskIterations(taskId);
      setIterations(iterData);
      if (iterData.length > 0) {
        setCurrentIteration(iterData[iterData.length - 1]);
      }
    } catch (err: any) {
      setActionError(err?.message || 'Unable to load this task. Check the connection and try again.');
    } finally {
      setLoading(false);
    }
  };

  const loadTabData = async (tab: string) => {
    if (!taskId) return;
    setActiveTab(tab);
    setActionError('');
    try {
      if (tab === 'rules' && rules.length === 0) {
        const data = await api.getTaskRules(taskId);
        setRules(data);
      } else if (tab === 'learnings' && learnings.length === 0) {
        const data = await api.getTaskLearnings(taskId);
        setLearnings(data);
      } else if (tab === 'snapshots' && snapshots.length === 0) {
        const data = await api.getTaskSnapshots(taskId);
        setSnapshots(data);
      }
    } catch (err: any) {
      setActionError(err?.message || 'Unable to load this section. Try again.');
    }
  };

  const [togglingLearning, setTogglingLearning] = useState(false);

  const handleToggleLearning = async () => {
    if (!task || !taskId || togglingLearning) return;
    setTogglingLearning(true);
    setActionError('');
    const currentVal = Boolean(task.persistent_learning ?? task.use_persistent_learning);
    const nextVal = !currentVal;

    // Optimistic update
    setTask(prev => prev ? { ...prev, persistent_learning: nextVal, use_persistent_learning: nextVal } : prev);
    try {
      const updated = await api.toggleTaskLearning(taskId, nextVal);
      setTask(prev => prev ? {
        ...prev,
        persistent_learning: Boolean(updated.persistent_learning ?? updated.use_persistent_learning),
        use_persistent_learning: Boolean(updated.persistent_learning ?? updated.use_persistent_learning)
      } : prev);
    } catch (err: any) {
      setTask(prev => prev ? { ...prev, persistent_learning: currentVal, use_persistent_learning: currentVal } : prev);
      setActionError(err?.message || 'Unable to update this setting. Try again.');
    } finally {
      setTogglingLearning(false);
    }
  };

  const handleAction = async (action: 'start' | 'pause' | 'resume' | 'stop') => {
    if (!taskId) return;
    if (action === 'stop' && !window.confirm('Stop this run? The agent will finish after the current step.')) {
      return;
    }
    setBusyAction(action);
    setActionError('');
    try {
      if (action === 'start') await api.startTask(taskId);
      else if (action === 'pause') await api.pauseTask(taskId);
      else if (action === 'resume') await api.resumeTask(taskId);
      else if (action === 'stop') await api.stopTask(taskId);

      // Optimistic status update
      const newStatus = action === 'pause' ? 'PAUSED' : action === 'stop' ? 'STOPPED' : 'RUNNING';
      setTask(prev => prev ? { ...prev, status: newStatus as any } : null);
      window.setTimeout(() => {
        api.getTask(taskId).then(t => t && setTask(t)).catch(() => {});
      }, 400);
    } catch (err: any) {
      setActionError(err?.message || `Unable to ${action} the task. Try again.`);
    } finally {
      setBusyAction('');
    }
  };

  if (loading) return <div role="status" className="py-16 text-center text-sm text-slate-400">Loading task…</div>;

  if (!task) {
    return (
      <div role="alert" className="mx-auto max-w-xl rounded-lg border border-red-700/60 bg-red-950 px-4 py-3 text-sm text-red-200">
        <p>{actionError || 'This task could not be loaded. It may have been deleted.'}</p>
        <div className="mt-3 flex gap-2">
          <button type="button" onClick={fetchTaskData} className="btn-secondary px-3 py-1.5 text-xs">
            Try again
          </button>
          <Link to="/" className="btn-secondary px-3 py-1.5 text-xs">
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  const tabs = [
    { id: 'live', label: 'Live View' },
    { id: 'timeline', label: 'Timeline' },
    { id: 'rules', label: 'Rules' },
    { id: 'learnings', label: 'Learnings' },
    { id: 'snapshots', label: 'Snapshots' }
  ];

  const isPersistentLearningActive = Boolean(task.persistent_learning ?? task.use_persistent_learning);
  const status = (task.status || '').toLowerCase();
  const isCreated = status === 'created' || status === 'queued';
  const isRunning = status === 'running';
  const isPaused = status === 'paused';
  const isStopped = status === 'stopped';

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <header className="card p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-bold">{task.title}</h1>
              <StatusBadge status={task.status} />
            </div>
            <p className="max-w-3xl text-sm leading-relaxed text-slate-400">{task.description}</p>
          </div>

          <div className="flex flex-wrap gap-2">
            {isCreated && (
              <button type="button" onClick={() => handleAction('start')} disabled={busyAction === 'start'} className="btn-primary">
                {busyAction === 'start' ? 'Starting…' : 'Start'}
              </button>
            )}
            {isRunning && (
              <>
                <button type="button" onClick={() => handleAction('pause')} disabled={busyAction === 'pause'} className="btn-warn">
                  {busyAction === 'pause' ? 'Pausing…' : 'Pause'}
                </button>
                <button type="button" onClick={() => handleAction('stop')} disabled={busyAction === 'stop'} className="btn-danger">
                  {busyAction === 'stop' ? 'Stopping…' : 'Stop'}
                </button>
              </>
            )}
            {isPaused && (
              <>
                <button type="button" onClick={() => handleAction('resume')} disabled={busyAction === 'resume'} className="btn-primary">
                  {busyAction === 'resume' ? 'Resuming…' : 'Resume'}
                </button>
                <button type="button" onClick={() => handleAction('stop')} disabled={busyAction === 'stop'} className="btn-danger">
                  {busyAction === 'stop' ? 'Stopping…' : 'Stop'}
                </button>
              </>
            )}
            {isStopped && (
              <button type="button" onClick={() => handleAction('resume')} disabled={busyAction === 'resume'} className="btn-primary">
                {busyAction === 'resume' ? 'Resuming…' : 'Resume'}
              </button>
            )}
          </div>
        </div>

        {actionError && (
          <div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-700/60 bg-red-950 px-4 py-3 text-sm text-red-200">
            <span>{actionError}</span>
            <button type="button" onClick={fetchTaskData} className="btn-secondary px-3 py-1.5 text-xs">
              Refresh
            </button>
          </div>
        )}

        <dl className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
          <div className="flex items-center gap-2">
            <dt className="text-slate-400">Model</dt>
            <dd className="text-slate-200">{task.model}</dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="text-slate-400">Temperature</dt>
            <dd className="num text-slate-200">{task.temperature}</dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="text-slate-400">Iteration limit</dt>
            <dd className="num text-slate-200">{task.max_iterations}</dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="text-slate-400">Stored learnings</dt>
            <dd>
              <button
                type="button"
                aria-pressed={isPersistentLearningActive}
                onClick={handleToggleLearning}
                disabled={togglingLearning}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold transition-colors disabled:opacity-60 ${
                  isPersistentLearningActive
                    ? 'border-emerald-700/60 bg-emerald-950 text-emerald-300 hover:bg-emerald-900'
                    : 'border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 rounded-full ${isPersistentLearningActive ? 'bg-emerald-400' : 'bg-slate-400'}`}
                />
                {isPersistentLearningActive ? 'On' : 'Off'}
              </button>
            </dd>
          </div>
        </dl>
      </header>

      {/* Tabs */}
      <div role="tablist" aria-label="Task views" className="flex shrink-0 flex-wrap border-b border-slate-700 sm:flex-nowrap sm:overflow-x-auto">
        {tabs.map(tab => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls={`panel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => loadTabData(tab.id)}
            onKeyDown={(e) => {
              if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
              e.preventDefault();
              const index = tabs.findIndex(t => t.id === activeTab);
              const offset = e.key === 'ArrowRight' ? 1 : tabs.length - 1;
              const next = tabs[(index + offset) % tabs.length];
              loadTabData(next.id);
              document.getElementById(`tab-${next.id}`)?.focus();
            }}
            className={`tab ${activeTab === tab.id ? 'tab-active' : ''}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content Area */}
      <div
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        className="min-h-0 flex-1 rounded-xl bg-slate-800/20 p-2"
      >
        {activeTab === 'live' && (
          <ErrorBoundary fallbackTitle="Live Iteration Display">
            <LiveIterationView iteration={currentIteration} status={task?.status} />
          </ErrorBoundary>
        )}
        
        {activeTab === 'timeline' && (
          <ErrorBoundary fallbackTitle="Timeline">
            <div className="mx-auto max-w-4xl space-y-4 p-2">
              {learnings.length === 0 && (
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-8 text-center text-sm text-slate-400">
                  No events recorded yet. Events appear as the agent learns during a run.
                </div>
              )}
              {learnings.map(learning => (
                <EventCard 
                  key={learning.id}
                  iterationNumber={learning.iteration_number}
                  category={learning.category}
                  content={learning.content}
                  date={learning.created_at}
                />
              ))}
            </div>
          </ErrorBoundary>
        )}

        {activeTab === 'rules' && (
          <ErrorBoundary fallbackTitle="Rules">
            <div className="grid grid-cols-1 gap-4 p-2 md:grid-cols-2 lg:grid-cols-3">
              {rules.length === 0 && (
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-8 text-center text-sm text-slate-400 md:col-span-2 lg:col-span-3">
                  No rules yet. Rules are promoted from repeated, consistent observations during a run.
                </div>
              )}
              {rules.map(rule => (
                <RuleCard key={rule.id} rule={rule} />
              ))}
            </div>
          </ErrorBoundary>
        )}

        {activeTab === 'learnings' && (
          <ErrorBoundary fallbackTitle="Learnings">
            <div className="mx-auto max-w-4xl space-y-4 p-2">
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={async () => {
                    if (!taskId) return;
                    try {
                      const blob = await api.downloadLearnings(taskId);
                      const url = window.URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = `learnings-${taskId}.json`;
                      a.click();
                      window.URL.revokeObjectURL(url);
                    } catch (err: any) {
                      setActionError(err?.message || 'Unable to download the file. Try again.');
                    }
                  }}
                  className="btn-secondary px-3 py-1.5 text-xs"
                >
                  Download learnings
                </button>
              </div>
              {learnings.length === 0 && (
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-8 text-center text-sm text-slate-400">
                  No learnings recorded yet. Learnings are written after every iteration.
                </div>
              )}
              {learnings.map(l => (
                <article key={l.id} className="card flex flex-col gap-2 p-4">
                   <div className="flex justify-between gap-3">
                      <span className="num font-mono text-xs text-slate-400">Iteration {l.iteration_number}</span>
                      <span className="badge-neutral">{l.category}</span>
                   </div>
                   <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">{l.content}</p>
                </article>
              ))}
            </div>
          </ErrorBoundary>
        )}

        {activeTab === 'snapshots' && (
          <ErrorBoundary fallbackTitle="Snapshots">
            <div className="space-y-4 p-2">
              <p className="max-w-3xl text-sm text-slate-400">
                Snapshots capture the agent’s rules, discoveries and strategy at a fixed interval.
              </p>
              {snapshots.length === 0 && (
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-8 text-center text-sm text-slate-400">
                  No snapshots yet. The first snapshot is taken at the configured interval.
                </div>
              )}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
                {snapshots.map(s => (
                  <article key={s.id} className="card p-4">
                    <div className="num font-semibold text-slate-200">Iteration {s.iteration_number}</div>
                    <time dateTime={s.created_at} className="num text-xs text-slate-400">
                      {new Date(s.created_at).toLocaleString()}
                    </time>
                  </article>
                ))}
              </div>
            </div>
          </ErrorBoundary>
        )}
      </div>
    </div>
  );
};

export default TaskDetailPage;
