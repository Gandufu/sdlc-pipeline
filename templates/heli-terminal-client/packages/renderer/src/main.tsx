import { Component, ErrorInfo, ReactNode } from 'react';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';

interface EBState { err: Error | null }
class ErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  state: EBState = { err: null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  componentDidCatch(err: Error, info: ErrorInfo) {
    // 临时诊断：直接显示在窗口，并把错误追加到 sessionStorage
    // 让 DevTools / 后续 inspection 能拿到
    try { sessionStorage.setItem('__lastError', JSON.stringify({ msg: err.message, stack: err.stack, info: info.componentStack })); } catch {}
    console.error('[ErrorBoundary]', err, info);
  }
  render() {
    if (this.state.err) {
      return (
        <div style={{ padding: 24, fontFamily: 'monospace', color: '#a00', whiteSpace: 'pre-wrap' }}>
          <h2>渲染错误</h2>
          <p><b>{this.state.err.message}</b></p>
          <p style={{ fontSize: 12 }}>{this.state.err.stack}</p>
          <hr />
          <p style={{ fontSize: 12, color: '#666' }}>
            错误已写入 sessionStorage.__lastError
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
