import React from 'react'
import ReactDOM from 'react-dom/client'
import './globals.css'
import App from './App'
import { AppErrorBoundary } from './components/shared/AppErrorBoundary'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element #root not found in index.html')
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>
)
