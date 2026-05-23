import { useCallback, useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL || '/api'
const POLL_INTERVAL = 60_000

export default function ScannerPanel() {
  const [movers, setMovers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetch(`${API}/scanner/movers`)
      .then(r => r.ok ? r.json() : r.json().then(b => Promise.reject(b.detail || r.statusText)))
      .then(data => { setMovers(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, POLL_INTERVAL)
    return () => clearInterval(id)
  }, [load])

  return (
    <div className="panel">
      <div className="panel-header" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Scanner — Top Movers</h2>
        <button onClick={load} disabled={loading} style={{
          background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          color: loading ? 'var(--text-muted)' : 'var(--text)', padding: '3px 10px',
          fontSize: 11, cursor: loading ? 'default' : 'pointer',
        }}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && <p className="error">Error: {error}</p>}

      {!loading && !error && movers.length === 0 && (
        <p className="status">No movers found.</p>
      )}

      {movers.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Price</th>
                <th>Change %</th>
                <th>Volume</th>
                <th>High</th>
                <th>Low</th>
              </tr>
            </thead>
            <tbody>
              {movers.map(m => (
                <tr key={m.ticker}>
                  <td><strong>{m.ticker}</strong></td>
                  <td>${m.price?.toFixed(2)}</td>
                  <td className={m.change_pct >= 0 ? 'up' : 'down'}>
                    {m.change_pct >= 0 ? '+' : ''}{m.change_pct?.toFixed(2)}%
                  </td>
                  <td>{m.volume?.toLocaleString()}</td>
                  <td>${m.high?.toFixed(2)}</td>
                  <td>${m.low?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
