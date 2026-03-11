import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("ErrorBoundary caught:", error, errorInfo);
  }

  private handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback;
    }

    return (
      <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-4">
        <p className="text-sm font-medium text-red-400">Something went wrong</p>
        <p className="mt-1 text-xs text-gray-500">
          {this.state.error?.message ?? "Unknown error"}
        </p>
        <button
          className="mt-3 text-xs text-gray-400 underline hover:text-gray-200"
          onClick={this.handleReset}
        >
          Try again
        </button>
      </div>
    );
  }
}

export default ErrorBoundary;
