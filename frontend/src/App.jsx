import ScannerPanel from './components/ScannerPanel'
import SentimentFeed from './components/SentimentFeed'
import PortfolioView from './components/PortfolioView'

export default function App() {
  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: '24px 16px' }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 16, fontWeight: 700, letterSpacing: '0.04em' }}>
          AI Trading Dashboard
        </h1>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <ScannerPanel />
        <SentimentFeed />
      </div>

      <PortfolioView />
    </div>
  )
}
