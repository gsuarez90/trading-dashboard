import { useCallback, useState } from 'react'
import { apiFetch } from '../utils/api'

const DIR_STYLE = {
  long:  { background: '#1a3a2a', color: '#3fb950' },
  short: { background: '#3a1a1a', color: '#f85149' },
}

const REASON_LABEL = {
  target_hit:  'Target hit',
  stop_hit:    'Stop hit',
  manual:      'Manual',
  eod_close:   'EOD close',
  kill_switch: 'Kill switch',
  expired:     'Expired (unfilled)',
}

function fmt(n, prefix = '$') {
  if (n == null) return '—'
  const abs = Math.abs(n).toFixed(2)
  return n < 0 ? `-${prefix}${abs}` : `${prefix}${abs}`
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

// ── Summary bar ──────────────────────────────────────────────────────────────

function SummaryBar({ summary }) {
  if (!summary) return null
  const pnlColor = summary.realized_pnl >= 0 ? 'var(--green)' : 'var(--red)'
  const pct = summary.goal > 0 ? Math.min(100, (summary.realized_pnl / summary.goal) * 100) : 0

  return (
    <div style={{
      background: 'var(--surface)', borderRadius: 'var(--radius)',
      padding: '10px 14px', marginBottom: 14,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Realized P&L <strong style={{ fontSize: 14, color: pnlColor, fontFamily: 'var(--mono)' }}>
            {fmt(summary.realized_pnl)}
          </strong>
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Goal <strong style={{ color: 'var(--text)', fontFamily: 'var(--mono)' }}>${summary.goal}</strong>
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Open <strong style={{ color: 'var(--text)' }}>{summary.open_positions}</strong>
        </span>
        {summary.goal_hit && (
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
            background: '#1a3a2a', color: 'var(--green)',
          }}>
            GOAL HIT {summary.goal_hit_time ? `@ ${fmtTime(summary.goal_hit_time)}` : ''}
          </span>
        )}
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {summary.settlement_note}
        </span>
      </div>

      {/* goal progress bar */}
      <div style={{ height: 4, background: '#2a2a2a', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${Math.max(0, pct)}%`,
          background: summary.goal_hit ? 'var(--green)' : '#d29922',
          borderRadius: 2, transition: 'width 0.4s ease',
        }} />
      </div>
    </div>
  )
}

// ── Open position row ─────────────────────────────────────────────────────────

function OpenRow({ trade, onClose }) {
  const [open, setOpen]   = useState(false)
  const [price, setPrice] = useState('')
  const [busy, setBusy]   = useState(false)
  const [err, setErr]     = useState(null)

  const dir = DIR_STYLE[trade.direction] ?? DIR_STYLE.long

  function submit() {
    const p = parseFloat(price)
    if (isNaN(p) || p <= 0) { setErr('Enter a valid price'); return }
    setBusy(true)
    setErr(null)
    apiFetch(`/paper-trades/${trade.trade_id}/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exit_price: p, close_reason: 'manual' }),
    })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail ?? r.statusText)))
      .then(() => { setBusy(false); onClose() })
      .catch(e => { setErr(String(e)); setBusy(false) })
  }

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 'var(--radius)',
      padding: 12, marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 13, fontFamily: 'var(--mono)', minWidth: 52 }}>{trade.ticker}</strong>
        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 10, ...dir }}>
          {trade.direction.toUpperCase()}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {trade.shares} sh @ <span style={{ fontFamily: 'var(--mono)' }}>${trade.entry_price.toFixed(2)}</span>
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          T <span style={{ fontFamily: 'var(--mono)', color: 'var(--green)' }}>${trade.target_price.toFixed(2)}</span>
          {' / '}
          S <span style={{ fontFamily: 'var(--mono)', color: 'var(--red)' }}>${trade.stop_loss.toFixed(2)}</span>
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {fmtTime(trade.entry_time)}
        </span>
        <button onClick={() => setOpen(o => !o)} style={{
          fontSize: 11, padding: '2px 10px', borderRadius: 'var(--radius)',
          border: '1px solid var(--border)', background: open ? 'var(--surface)' : 'none',
          color: 'var(--text-muted)', cursor: 'pointer',
        }}>
          {open ? 'Cancel' : 'Close'}
        </button>
      </div>

      {open && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
          <input
            type="number"
            step="0.01"
            placeholder="Exit price"
            value={price}
            onChange={e => setPrice(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()}
            style={{
              width: 110, background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius)', color: 'var(--text)', fontSize: 12,
              padding: '4px 8px', outline: 'none',
            }}
          />
          <button onClick={submit} disabled={busy} style={{
            fontSize: 11, padding: '4px 12px', borderRadius: 'var(--radius)',
            border: '1px solid var(--border)', cursor: busy ? 'default' : 'pointer',
            background: busy ? 'var(--surface)' : '#1c2d3d',
            color: busy ? 'var(--text-muted)' : 'var(--blue)', fontWeight: 600,
          }}>
            {busy ? 'Closing…' : 'Confirm'}
          </button>
          {err && <span style={{ fontSize: 11, color: 'var(--red)' }}>{err}</span>}
        </div>
      )}
    </div>
  )
}

// ── Pending order row ─────────────────────────────────────────────────────────

function PendingRow({ trade }) {
  const dir = DIR_STYLE[trade.direction] ?? DIR_STYLE.long

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 'var(--radius)',
      padding: 12, marginBottom: 8, opacity: 0.85,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 13, fontFamily: 'var(--mono)', minWidth: 52 }}>{trade.ticker}</strong>
        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 10, ...dir }}>
          {trade.direction.toUpperCase()}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {trade.shares} sh
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Limit <span style={{ fontFamily: 'var(--mono)', color: 'var(--text)' }}>
            ${(trade.limit_price ?? trade.entry_price).toFixed(2)}
          </span>
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          T <span style={{ fontFamily: 'var(--mono)', color: 'var(--green)' }}>${trade.target_price.toFixed(2)}</span>
          {' / '}
          S <span style={{ fontFamily: 'var(--mono)', color: 'var(--red)' }}>${trade.stop_loss.toFixed(2)}</span>
        </span>
        <span style={{
          fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
          background: '#1c2d1c', color: '#d29922', marginLeft: 'auto',
        }}>
          PENDING
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          {fmtTime(trade.pending_since)}
        </span>
      </div>
    </div>
  )
}

// ── History row ───────────────────────────────────────────────────────────────

function HistoryRow({ trade }) {
  const pnl = trade.realized_pnl ?? 0
  const pnlColor = pnl >= 0 ? 'var(--green)' : 'var(--red)'
  const dir = DIR_STYLE[trade.direction] ?? DIR_STYLE.long

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
      padding: '8px 0', borderBottom: '1px solid var(--border)', fontSize: 12,
    }}>
      <strong style={{ fontFamily: 'var(--mono)', minWidth: 52 }}>{trade.ticker}</strong>
      <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 10, ...dir }}>
        {trade.direction.toUpperCase()}
      </span>
      <span style={{ color: 'var(--text-muted)' }}>
        {trade.shares} sh
      </span>
      <span style={{ fontFamily: 'var(--mono)', color: 'var(--text-muted)' }}>
        ${trade.entry_price.toFixed(2)} → {trade.exit_price != null ? `$${trade.exit_price.toFixed(2)}` : '—'}
      </span>
      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
        {REASON_LABEL[trade.close_reason] ?? trade.close_reason ?? '—'}
      </span>
      <span style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: pnlColor, marginLeft: 'auto' }}>
        {fmt(pnl)}
      </span>
      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{fmtTime(trade.exit_time)}</span>
    </div>
  )
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

function OpenTab({ trades, onClose }) {
  const open = trades.filter(t => t.status === 'open')
  if (open.length === 0) return <p className="status">No open positions today.</p>
  return open.map(t => <OpenRow key={t.trade_id} trade={t} onClose={onClose} />)
}

function PendingTab({ pending }) {
  if (pending.length === 0) return <p className="status">No pending orders today.</p>
  return pending.map(t => <PendingRow key={t.trade_id} trade={t} />)
}

function HistoryTab({ trades }) {
  const closed = trades.filter(t => t.status !== 'open' && t.status !== 'pending')
  if (closed.length === 0) return <p className="status">No closed trades today.</p>
  return (
    <div>
      {closed.map(t => <HistoryRow key={t.trade_id} trade={t} />)}
    </div>
  )
}

function SummaryTab({ summary }) {
  if (!summary) return <p className="status">Loading…</p>
  const pnlColor = summary.realized_pnl >= 0 ? 'var(--green)' : 'var(--red)'

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
      {[
        ['Date',          summary.date],
        ['Realized P&L',  fmt(summary.realized_pnl), pnlColor],
        ['Daily Goal',    `$${summary.goal}`],
        ['Open Positions',summary.open_positions],
        ['Goal Hit',      summary.goal_hit ? `Yes @ ${fmtTime(summary.goal_hit_time)}` : 'Not yet'],
        ['Mode',          summary.trading_mode],
      ].map(([label, val, color]) => (
        <div key={label} style={{
          background: 'var(--surface)', borderRadius: 4, padding: '8px 12px',
        }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
          <div style={{ fontSize: 13, fontFamily: 'var(--mono)', fontWeight: 600, color: color ?? 'var(--text)' }}>
            {val}
          </div>
        </div>
      ))}
      <div style={{
        gridColumn: '1 / -1', background: 'var(--surface)', borderRadius: 4, padding: '8px 12px',
      }}>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Settlement</div>
        <div style={{ fontSize: 12, color: 'var(--text)' }}>{summary.settlement_note}</div>
      </div>
    </div>
  )
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export default function PaperTradingPanel() {
  const [tab, setTab]           = useState('open')
  const [expanded, setExpanded] = useState(true)
  const [trades, setTrades]     = useState([])
  const [pending, setPending]   = useState([])
  const [summary, setSummary]   = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      apiFetch('/paper-trades/', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.statusText)),
      apiFetch('/paper-trades/pending', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.statusText)),
      apiFetch('/paper-trades/summary', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.statusText)),
    ])
      .then(([t, p, s]) => { setTrades(t); setPending(p); setSummary(s); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  // load on first expand
  const [loaded, setLoaded] = useState(false)
  function toggleExpand() {
    setExpanded(e => {
      if (!e && !loaded) { load(); setLoaded(true) }
      return !e
    })
  }

  const TABS = ['open', 'pending', 'history', 'summary']

  return (
    <div className="panel">
      <div className="panel-header" style={{ marginBottom: expanded ? 14 : 0 }}>
        <button onClick={toggleExpand} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6, padding: 0,
        }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{expanded ? '▼' : '▶'}</span>
          <h2 style={{ margin: 0 }}>Paper Trading</h2>
        </button>

        {expanded && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ display: 'flex', gap: 4 }}>
              {TABS.map(t => {
                const count =
                  t === 'open'    ? trades.filter(x => x.status === 'open').length :
                  t === 'pending' ? pending.length : 0
                const label = t.charAt(0).toUpperCase() + t.slice(1)
                return (
                  <button key={t} onClick={() => setTab(t)} style={{
                    background: tab === t ? 'var(--surface)' : 'none',
                    border: `1px solid ${tab === t ? 'var(--border)' : 'transparent'}`,
                    borderRadius: 'var(--radius)', color: tab === t ? 'var(--text)' : 'var(--text-muted)',
                    padding: '3px 10px', fontSize: 11, cursor: 'pointer', fontWeight: tab === t ? 600 : 400,
                  }}>
                    {count > 0 ? `${label} (${count})` : label}
                  </button>
                )
              })}
            </div>
            <button onClick={load} disabled={loading} style={{
              background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              color: loading ? 'var(--text-muted)' : 'var(--text)', padding: '3px 10px',
              fontSize: 11, cursor: loading ? 'default' : 'pointer',
            }}>
              {loading ? 'Loading…' : 'Refresh'}
            </button>
          </div>
        )}
      </div>

      {expanded && (
        <>
          {error && <p className="error">Error: {error}</p>}
          {!error && !loading && (
            <>
              <SummaryBar summary={summary} />
              {tab === 'open'    && <OpenTab    trades={trades} onClose={load} />}
              {tab === 'pending' && <PendingTab pending={pending} />}
              {tab === 'history' && <HistoryTab trades={trades} />}
              {tab === 'summary' && <SummaryTab summary={summary} />}
            </>
          )}
          {loading && <p className="status">Loading…</p>}
        </>
      )}
    </div>
  )
}
