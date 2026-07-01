import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'
import { recordError } from './errorLog.js'

// ErrorBoundaryが拾えないもの（イベントハンドラ内・Promise内のエラー）も記録する
window.addEventListener('error', (e) => recordError(e.error ?? e.message))
window.addEventListener('unhandledrejection', (e) => recordError(e.reason))

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
