import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div role="alert" className="mx-auto my-4 max-w-lg rounded-xl border border-red-700/50 bg-slate-900 p-6 text-center">
          <h2 className="mb-2 text-base font-semibold text-slate-100">
            {this.props.fallbackTitle || 'This section'} didn’t load
          </h2>
          <p className="mb-5 text-sm text-slate-400">
            Something went wrong while rendering this view. Try again, or reload the page if it keeps happening.
          </p>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, error: null })}
            className="btn-secondary"
          >
            Try again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
