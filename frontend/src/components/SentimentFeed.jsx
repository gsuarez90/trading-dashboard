import { useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL || '/api'

const TICKERS = 'AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,SPY,QQQ,AMD,NFLX,ORCL,CRM,PLTR'

function labelClass(label) {
  if (label === 'bullish') return 'up'
  if (label === 'bearish') return 'down'
  return 'neutral'
}

export default function SentimentFeed() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/sentiment/batch/scores?tickers=${TICKERS}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(data => { setRows(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  return (
    <div className="panel">
      <h2>Sentiment — 3-Day News</h2>

      {loading && <p className="status">Loading…</p>}
      {error   && <p className="error">Error: {error}</p>}

      {!loading && !error && rows.length === 0 && (
        <p className="status">No sentiment data.</p>
      )}

      {rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Score</th>
              <th>Label</th>
              <th>Articles</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.ticker}>
                <td><strong>{r.ticker}</strong></td>
                <td className={labelClass(r.label)}>{r.score?.toFixed(4)}</td>
                <td>
                  <span className={`badge badge-${r.label === 'bullish' ? 'positive' : r.label === 'bearish' ? 'negative' : 'neutral'}`}>
                    {r.label}
                  </span>
                </td>
                <td>{r.article_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
