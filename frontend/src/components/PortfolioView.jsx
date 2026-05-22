import { useCallback, useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL || '/api'
const POLL_INTERVAL = 90_000

export default function PortfolioView() {
  const [portfolio, setPortfolio] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetch(`${API}/portfolio/`)
      .then(r => r.ok ? r.json() : r.json().then(b => Promise.reject(b.detail || r.statusText)))
      .then(data => { setPortfolio(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, POLL_INTERVAL)
    return () => clearInterval(id)
  }, [load])

  const positions = portfolio?.positions || []

  return (
    <div className="panel">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Portfolio</h2>
        <button onClick={load} disabled={loading} style={{
          background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          color: loading ? 'var(--text-muted)' : 'var(--text)', padding: '3px 10px',
          fontSize: 11, cursor: loading ? 'default' : 'pointer',
        }}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && <p className="error">Error: {error}</p>}

      {portfolio && (
        <>
          <p style={{ marginBottom: 12, fontFamily: 'var(--mono)', fontSize: 13 }}>
            Cash: <strong>${portfolio.cash?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
          </p>

          {positions.length === 0 ? (
            <p className="status">No open positions.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Shares</th>
                  <th>Avg Cost</th>
                  <th>Price</th>
                  <th>Unreal. P&L</th>
                  <th>%</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(p => (
                  <tr key={p.ticker}>
                    <td><strong>{p.ticker}</strong></td>
                    <td>{p.shares}</td>
                    <td>${p.avg_cost?.toFixed(2)}</td>
                    <td>${p.current_price?.toFixed(2) ?? '—'}</td>
                    <td className={p.unrealized_pnl >= 0 ? 'up' : 'down'}>
                      {p.unrealized_pnl != null
                        ? `${p.unrealized_pnl >= 0 ? '+' : ''}$${p.unrealized_pnl.toFixed(2)}`
                        : '—'}
                    </td>
                    <td className={p.unrealized_pnl_pct >= 0 ? 'up' : 'down'}>
                      {p.unrealized_pnl_pct != null
                        ? `${p.unrealized_pnl_pct >= 0 ? '+' : ''}${p.unrealized_pnl_pct.toFixed(2)}%`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  )
}
