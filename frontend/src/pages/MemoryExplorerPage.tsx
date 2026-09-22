import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { MemorySearchResult, MemoryStats } from '../types';
import ConfidenceBar from '../components/ConfidenceBar';

const MemoryExplorerPage = () => {
  const [query, setQuery] = useState('');
  const [lastQuery, setLastQuery] = useState('');
  const [results, setResults] = useState<MemorySearchResult[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const data = await api.getMemoryStats();
      setStats(data);
    } catch {
      // Stats are supporting context; the search below still works without them.
    }
  };

  const runSearch = async (term: string) => {
    const trimmed = term.trim();
    if (!trimmed) return;

    setLoading(true);
    setError('');
    try {
      const data = await api.searchMemory(trimmed);
      setResults(Array.isArray(data) ? data : []);
      setLastQuery(trimmed);
      setSearched(true);
    } catch (err: any) {
      setError(err?.message || 'Unable to search memory. Check the connection and try again.');
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    runSearch(query);
  };

  const clearSearch = () => {
    setQuery('');
    setResults([]);
    setSearched(false);
    setError('');
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-bold">Memory Explorer</h1>

      {stats && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <div className="card p-4 text-center">
            <div className="mb-1 text-xs text-slate-400">Total memories</div>
            <div className="num text-2xl font-bold text-slate-100">{stats.total_memories}</div>
          </div>
          <div className="card p-4 text-center">
            <div className="mb-1 text-xs text-slate-400">Generalizable</div>
            <div className="num text-2xl font-bold text-blue-300">{stats.global_count}</div>
          </div>
          <div className="card p-4 text-center">
            <div className="mb-1 text-xs text-slate-400">Task specific</div>
            <div className="num text-2xl font-bold text-violet-300">{stats.task_count}</div>
          </div>
          <div className="card p-4 text-center">
            <div className="mb-1 text-xs text-slate-400">Average confidence</div>
            <div className="num text-2xl font-bold text-emerald-300">
              {Number.isFinite(stats.avg_confidence)
                ? `${Math.round(stats.avg_confidence * 100)}%`
                : '—'}
            </div>
          </div>
        </div>
      )}

      <form onSubmit={handleSearch} className="flex flex-wrap items-end gap-2">
        <div className="min-w-[16rem] flex-1">
          <label htmlFor="memory-search" className="label">
            Search memories
          </label>
          <input
            id="memory-search"
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="e.g. API error handling strategies"
            className="input"
          />
        </div>
        <button type="submit" disabled={loading || !query.trim()} className="btn-primary">
          {loading ? 'Searching…' : 'Search'}
        </button>
      </form>

      <div role="status" className="sr-only">
        {searched && !loading
          ? results.length > 0
            ? `${results.length} results for ${lastQuery}`
            : `No results for ${lastQuery}`
          : ''}
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-red-700/60 bg-red-950 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <div aria-busy={loading} className="space-y-4">
        {results.length > 0 ? (
          results.map(result => (
            <article key={result.id} className="card p-5 transition-colors hover:border-slate-600">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="badge-neutral">{result.metadata?.category || 'General'}</span>
                  <span className="num font-mono text-xs text-slate-400">
                    Score: {result.score.toFixed(3)}
                  </span>
                </div>
                {result.metadata?.confidence !== undefined && (
                  <div className="w-28">
                    <ConfidenceBar confidence={result.metadata.confidence} label="Memory confidence" />
                  </div>
                )}
              </div>
              <p className="leading-relaxed text-slate-200">{result.content}</p>

              {result.metadata?.task_id && (
                <div className="mt-3 flex flex-wrap justify-between gap-2 border-t border-slate-700/50 pt-3 text-xs text-slate-400">
                  <span className="truncate" title={result.metadata.task_id}>
                    Task: {result.metadata.task_id}
                  </span>
                  {result.metadata?.iteration_number && (
                    <span className="num">Iteration: {result.metadata.iteration_number}</span>
                  )}
                </div>
              )}
            </article>
          ))
        ) : searched && !loading && !error ? (
          <div className="card p-10 text-center">
            <p className="font-medium text-slate-200">No results for “{lastQuery}”</p>
            <p className="mx-auto mt-1 max-w-sm text-sm text-slate-400">
              Try different keywords, or clear the search to start again.
            </p>
            <button type="button" onClick={clearSearch} className="btn-secondary mt-5">
              Clear search
            </button>
          </div>
        ) : !searched && !loading ? (
          <div className="card p-10 text-center">
            <p className="font-medium text-slate-200">Search the knowledge store</p>
            <p className="mx-auto mt-1 max-w-sm text-sm text-slate-400">
              Every run stores synthesized learnings. Search them by meaning to see what the agent has picked up.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default MemoryExplorerPage;
