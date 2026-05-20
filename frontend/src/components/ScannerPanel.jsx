import { useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL || '/api'

export default function ScannerPanel() {
  const [movers, setMovers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/scanner/movers`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(data => { setMovers(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  return (
    <div className="panel">
      <h2>Scanner — Top Movers</h2>

      {loading && <p className="status">Loading…</p>}
      {error   && <p className="error">Error: {error}</p>}

      {!loading && !error && movers.length === 0 && (
        <p className="status">No movers found.</p>
      )}

      {movers.length > 0 && (
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
      )}
    </div>
  )
}
