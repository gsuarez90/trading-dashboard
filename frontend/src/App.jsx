import DailySummaryPanel from './components/DailySummaryPanel'
import ChatPanel from './components/ChatPanel'
import ScannerPanel from './components/ScannerPanel'
import SentimentFeed from './components/SentimentFeed'
import PortfolioView from './components/PortfolioView'
import PaperTradingPanel from './components/PaperTradingPanel'
import LiveTrackingPanel from './components/LiveTrackingPanel'
import GuardrailsPanel from './components/GuardrailsPanel'

export default function App() {
  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: '24px 16px' }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 16, fontWeight: 700, letterSpacing: '0.04em' }}>
          AI Trading Dashboard
        </h1>
      </header>

      <div style={{ marginBottom: 16 }}>
        <DailySummaryPanel />
      </div>

      <div style={{ marginBottom: 16 }}>
        <ChatPanel />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <ScannerPanel />
        <SentimentFeed />
      </div>

      <div style={{ marginBottom: 16 }}>
        <PaperTradingPanel />
      </div>

      <div style={{ marginBottom: 16 }}>
        <LiveTrackingPanel />
      </div>

      <div style={{ marginBottom: 16 }}>
        <GuardrailsPanel />
      </div>

      <PortfolioView />
    </div>
  )
}
