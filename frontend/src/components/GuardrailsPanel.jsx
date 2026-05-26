import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../utils/api'

const RULE_LABELS = {
  daily_loss_limit:     'Daily Loss Limit',
  position_size_cap:    'Position Size Cap',
  cost_basis_protection:'Cost Basis Protection',
  reward_risk_minimum:  'Reward/Risk Minimum',
  daily_trade_limit:    'Daily Trade Limit',
  market_hours_lock:    'Market Hours Lock',
  intraday_60min_cutoff:'Intraday 60-Min Cutoff',
  buying_power_check:   'Buying Power Check',
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

// ── Status cards ──────────────────────────────────────────────────────────────

function StatusCards({ status }) {
  if (!status) return null

  const loss    = status.daily_loss_limit
  const trades  = status.daily_trade_limit
  const hours   = status.market_hours

  const cards = [
    {
      label: 'Market',
      value: hours.in_session ? 'Open' : 'Closed',
      sub: hours.current_et,
      ok: hours.in_session,
    },
    {
      label: 'Intraday Window',
      value: hours.intraday_window_open ? 'Open' : 'Closed',
      sub: hours.intraday_window_open ? '>60 min remaining' : 'Past 3:00 PM ET',
      ok: hours.intraday_window_open,
    },
    {
      label: 'Daily Loss Limit',
      value: loss.triggered ? 'TRIGGERED' : 'OK',
      sub: `$${Math.abs(loss.realized_pnl_today).toFixed(2)} of $${loss.limit} limit`,
      ok: !loss.triggered,
    },
    {
      label: 'Daily Trades',
      value: trades.triggered ? 'LIMIT HIT' : 'OK',
      sub: `${trades.trades_today} of ${trades.limit} trades`,
      ok: !trades.triggered,
    },
  ]

  return (
    <div className="status-cards" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
      {cards.map(({ label, value, sub, ok }) => (
        <div key={label} style={{
          background: 'var(--surface)', borderRadius: 'var(--radius)',
          padding: '10px 12px',
          borderLeft: `3px solid ${ok ? 'var(--green)' : 'var(--red)'}`,
        }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>
          <div style={{
            fontSize: 13, fontWeight: 700, fontFamily: 'var(--mono)',
            color: ok ? 'var(--green)' : 'var(--red)',
          }}>
            {value}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>{sub}</div>
        </div>
      ))}
    </div>
  )
}

// ── Events log ────────────────────────────────────────────────────────────────

function EventsLog({ events }) {
  if (events.length === 0) {
    return <p className="status">No guardrail triggers today.</p>
  }

  return (
    <div>
      {events.map(e => (
        <div key={e.trade_id} style={{
          border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          padding: '10px 12px', marginBottom: 8,
          borderLeft: '3px solid var(--red)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <strong style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>{e.ticker}</strong>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>
              {fmtTime(e.timestamp)}
            </span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
            {(e.rules_triggered || []).map(rule => (
              <span key={rule} style={{
                fontSize: 10, fontWeight: 600, padding: '2px 6px', borderRadius: 10,
                background: '#3a1a1a', color: 'var(--red)',
              }}>
                {RULE_LABELS[rule] ?? rule}
              </span>
            ))}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {(e.messages || []).join(' · ')}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Kill switch ───────────────────────────────────────────────────────────────

function KillSwitch() {
  const [busy, setBusy]     = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError]   = useState(null)
  const [confirm, setConfirm] = useState(false)

  function fire() {
    if (!confirm) { setConfirm(true); return }
    setBusy(true)
    setError(null)
    apiFetch('/guardrails/kill-switch?confirmed=true', { method: 'POST' })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail ?? r.statusText)))
      .then(data => { setResult(data); setBusy(false); setConfirm(false) })
      .catch(e => { setError(String(e)); setBusy(false); setConfirm(false) })
  }

  return (
    <div style={{
      marginTop: 16, padding: '10px 12px', borderRadius: 'var(--radius)',
      background: '#1e0a0a', border: '1px solid #5a1a1a',
      display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
    }}>
      <span style={{ fontSize: 11, color: 'var(--red)', fontWeight: 600 }}>Kill Switch</span>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', flex: 1 }}>
        Closes all open paper trades. Flags live trades for manual close in Robinhood.
      </span>
      {result && (
        <span style={{ fontSize: 11, color: 'var(--green)' }}>
          Done — {result.paper_trades_closed} paper closed, {result.live_trades_flagged} live flagged
        </span>
      )}
      {error && <span style={{ fontSize: 11, color: 'var(--red)' }}>{error}</span>}
      <button onClick={fire} disabled={busy} style={{
        fontSize: 11, padding: '4px 12px', borderRadius: 'var(--radius)',
        border: '1px solid var(--red)', cursor: busy ? 'default' : 'pointer',
        background: confirm ? 'var(--red)' : 'none',
        color: confirm ? '#fff' : 'var(--red)',
        fontWeight: 600,
      }}>
        {busy ? 'Running…' : confirm ? 'Confirm — Close All' : 'Activate'}
      </button>
      {confirm && !busy && (
        <button onClick={() => setConfirm(false)} style={{
          fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius)',
          border: '1px solid var(--border)', background: 'none',
          color: 'var(--text-muted)', cursor: 'pointer',
        }}>
          Cancel
        </button>
      )}
    </div>
  )
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export default function GuardrailsPanel() {
  const [expanded, setExpanded] = useState(true)
  const [status, setStatus]     = useState(null)
  const [events, setEvents]     = useState([])
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      apiFetch('/guardrails/status', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.statusText)),
      apiFetch('/guardrails/events', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject(r.statusText)),
    ])
      .then(([s, e]) => { setStatus(s); setEvents(e); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  const [loaded, setLoaded] = useState(false)
  function toggleExpand() {
    setExpanded(e => {
      if (!e && !loaded) { load(); setLoaded(true) }
      return !e
    })
  }

  // Auto-refresh status every 60s (market hours change)
  useEffect(() => {
    load()
    setLoaded(true)
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, 60_000)
    return () => clearInterval(id)
  }, [load])

  return (
    <div className="panel">
      <div className="panel-header" style={{ marginBottom: expanded ? 14 : 0 }}>
        <button onClick={toggleExpand} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6, padding: 0,
        }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{expanded ? '▼' : '▶'}</span>
          <h2 style={{ margin: 0 }}>
            Guardrails
            {events.length > 0 && (
              <span style={{
                marginLeft: 8, fontSize: 10, fontWeight: 700,
                padding: '2px 6px', borderRadius: 10,
                background: '#3a1a1a', color: 'var(--red)',
              }}>
                {events.length} trigger{events.length !== 1 ? 's' : ''} today
              </span>
            )}
          </h2>
        </button>

        {expanded && (
          <button onClick={load} disabled={loading} style={{
            background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
            color: loading ? 'var(--text-muted)' : 'var(--text)', padding: '3px 10px',
            fontSize: 11, cursor: loading ? 'default' : 'pointer',
          }}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        )}
      </div>

      {expanded && (
        <>
          {error && <p className="error">Error: {error}</p>}
          {!error && !loading && (
            <>
              <StatusCards status={status} />
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600 }}>
                Today's Triggers
              </div>
              <EventsLog events={events} />
              <KillSwitch />
            </>
          )}
          {loading && <p className="status">Loading…</p>}
        </>
      )}
    </div>
  )
}
