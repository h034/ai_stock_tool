import { Component } from "react";
import { recordError } from "./errorLog";

const MAX_AUTO_RETRY = 3;

// ブラウザ拡張機能（翻訳・パスワードマネージャー等）がReact管理下のDOMを
// 書き換えることで発生する removeChild/insertBefore エラーをキャッチし、
// 画面が真っ白のまま固まるのを防ぐ。数回は自動で再マウントを試み、
// それでも解消しない場合のみ手動リロードを促す。
export default class ErrorBoundary extends Component {
  state = { hasError: false, retryCount: 0 };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    recordError(error, errorInfo?.componentStack);
    if (this.state.retryCount < MAX_AUTO_RETRY) {
      const retryCount = this.state.retryCount + 1;
      setTimeout(() => this.setState({ hasError: false, retryCount }), 50);
    }
  }

  render() {
    if (this.state.hasError) {
      if (this.state.retryCount < MAX_AUTO_RETRY) return null;
      return (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          height: "100vh", background: "#0f172a", color: "#f8fafc", gap: 12,
        }}>
          <p>表示の更新中に問題が発生しました。</p>
          <button
            onClick={() => window.location.reload()}
            style={{ padding: "8px 20px", borderRadius: 6, border: "none", background: "#3b82f6", color: "#fff", cursor: "pointer" }}
          >
            再読み込み
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
