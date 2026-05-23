import { useEffect, useState } from 'react'
import { getMarketStatus } from '../utils/market'

const API = import.meta.env.VITE_API_URL || '/api'

export default function DailySummaryPanel() {
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [expanded, setExpanded] = useState(true)

  function fetchBriefing() {
    setLoading(true)
    setError(null)
    fetch(`${API}/ai/briefing`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }

  useEffect(() => { fetchBriefing() }, [])

  const minsLeft = data?.minutes_remaining
  const marketOpen = minsLeft != null && minsLeft > 0

  return (
    <div className="panel">
      <div className="panel-header" style={{ marginBottom: expanded ? 12 : 0 }}>
        <button onClick={() => setExpanded(e => !e)} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6, padding: 0,
        }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1 }}>
            {expanded ? '▼' : '▶'}
          </span>
          <h2 style={{ margin: 0 }}>Morning Briefing</h2>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {data && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>
              {data.date}
              {minsLeft != null && (
                <span style={{ marginLeft: 8, color: marketOpen ? 'var(--green)' : 'var(--text-muted)' }}>
                  {marketOpen ? `${minsLeft}m remaining` : 'Market closed'}
                </span>
              )}
            </span>
          )}
          <button onClick={fetchBriefing} disabled={loading} style={{
            background: 'none',
            border: '1px solid var(--border)',
            color: loading ? 'var(--text-muted)' : 'var(--text)',
            borderRadius: 'var(--radius)',
            padding: '3px 10px',
            fontSize: 11,
            cursor: loading ? 'default' : 'pointer',
          }}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      {expanded && (
        <>
          {error && <p className="error">Error: {error}</p>}
          {!error && data && data.briefing && marketOpen && (
            <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, fontSize: 13, color: 'var(--text)' }}>
              {data.briefing}
            </p>
          )}
          {!error && data && (!marketOpen || !data.briefing) && (() => {
            const { isTodayTradingDay, nextOpenDate } = getMarketStatus()
            const msg = isTodayTradingDay
              ? 'Market closed — new briefing at market open (~9:35 AM ET).'
              : `Market closed — next briefing ${nextOpenDate}, ~9:35 AM ET.`
            return <p className="status">{msg}</p>
          })()}
          {loading && <p className="status">Loading…</p>}
        </>
      )}
    </div>
  )
}
