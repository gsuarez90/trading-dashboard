import { useRef, useState } from 'react'
import { useMarketStatus } from '../utils/market'
import { apiFetch } from '../utils/api'

const CONFIDENCE_STYLE = {
  high:   { background: '#1a3a2a', color: '#3fb950' },
  medium: { background: '#2a2a1a', color: '#d29922' },
  low:    { background: '#3a1a1a', color: '#f85149' },
}

function SuggestionCard({ trade, isRecommended, allowLoss }) {
  const [rhOpen, setRhOpen]   = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted]   = useState(false)
  const [submitErr, setSubmitErr]   = useState(null)
  const conf = CONFIDENCE_STYLE[trade.confidence] ?? CONFIDENCE_STYLE.low
  const pnlColor = (trade.current_unrealized_pnl ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'

  function paperTrade() {
    setSubmitting(true)
    setSubmitErr(null)
    apiFetch('/paper-trades/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ setup: trade, allow_loss: allowLoss ?? false }),
    })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail ?? r.statusText)))
      .then(() => { setSubmitted(true); setSubmitting(false) })
      .catch(e => { setSubmitErr(String(e)); setSubmitting(false) })
  }

  return (
    <div style={{
      border: `1px solid ${isRecommended ? '#3fb950' : 'var(--border)'}`,
      borderRadius: 'var(--radius)',
      padding: 14,
      marginBottom: 12,
      background: isRecommended ? '#0d1f12' : 'var(--bg)',
    }}>
      {/* card header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <strong style={{ fontSize: 14, fontFamily: 'var(--mono)' }}>{trade.ticker}</strong>
        <span style={{
          fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 10,
          background: trade.direction === 'long' ? '#1a3a2a' : '#3a1a1a',
          color: trade.direction === 'long' ? 'var(--green)' : 'var(--red)',
        }}>
          {trade.direction.toUpperCase()}
        </span>
        <span style={{ fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 10, ...conf }}>
          {trade.confidence.toUpperCase()}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {trade.trade_type.replace(/_/g, ' ')}
        </span>
        {isRecommended && (
          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)' }}>★ RECOMMENDED</span>
        )}
      </div>

      {/* price grid */}
      <div className="price-grid">
        {[
          ['Entry',    `$${trade.entry_price.toFixed(2)}`],
          ['Target',   `$${trade.target_price.toFixed(2)}`],
          ['Stop',     `$${trade.stop_loss.toFixed(2)}`],
          ['Shares',   trade.shares],
          ['Exp. Gain',`+$${trade.expected_gain.toFixed(0)}`],
          ['Max Loss', `-$${trade.max_loss.toFixed(0)}`],
        ].map(([label, val]) => (
          <div key={label} style={{ background: 'var(--surface)', borderRadius: 4, padding: '6px 8px' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
            <div style={{ fontSize: 12, fontFamily: 'var(--mono)', fontWeight: 600 }}>{val}</div>
          </div>
        ))}
      </div>

      {/* R/R + holding context */}
      <div style={{ display: 'flex', gap: 16, fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
        <span>R/R <strong style={{ color: 'var(--text)' }}>{trade.reward_risk_ratio.toFixed(2)}</strong></span>
        {trade.uses_existing_holding && trade.cost_basis != null && (
          <span>Cost basis <strong style={{ color: 'var(--text)' }}>${trade.cost_basis.toFixed(2)}</strong></span>
        )}
        {trade.current_unrealized_pnl != null && (
          <span>Unrealized P&L <strong style={{ color: pnlColor }}>${trade.current_unrealized_pnl.toFixed(0)}</strong></span>
        )}
      </div>

      {/* rationale */}
      <p style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 10 }}>
        {trade.rationale}
      </p>

      {/* paper trade action */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <button onClick={paperTrade} disabled={submitting || submitted} style={{
          fontSize: 11, padding: '4px 14px', borderRadius: 'var(--radius)',
          border: '1px solid var(--border)', cursor: submitting || submitted ? 'default' : 'pointer',
          background: submitted ? '#1a3a2a' : submitting ? 'var(--surface)' : '#1c2d3d',
          color: submitted ? 'var(--green)' : submitting ? 'var(--text-muted)' : 'var(--blue)',
          fontWeight: 600,
        }}>
          {submitted ? '✓ Paper Trade Logged' : submitting ? 'Submitting…' : 'Paper Trade'}
        </button>
        {submitErr && (
          <span style={{ fontSize: 11, color: 'var(--red)' }}>{submitErr}</span>
        )}
      </div>

      {/* robinhood instructions */}
      <button onClick={() => setRhOpen(o => !o)} style={{
        background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
        color: 'var(--text-muted)', fontSize: 11, padding: '3px 10px', cursor: 'pointer', width: '100%',
        textAlign: 'left',
      }}>
        {rhOpen ? '▼' : '▶'} Robinhood Instructions
      </button>
      {rhOpen && (
        <p style={{
          fontSize: 12, lineHeight: 1.7, marginTop: 8, padding: '8px 10px',
          background: 'var(--surface)', borderRadius: 4, whiteSpace: 'pre-wrap',
          color: 'var(--text)',
        }}>
          {trade.robinhood_instructions}
        </p>
      )}
    </div>
  )
}

function SuggestTab() {
  const [result, setResult]     = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const [allowLoss, setAllowLoss] = useState(false)
  const { open: marketOpen, closedRange } = useMarketStatus()

  function fetchSuggestions() {
    setLoading(true)
    setError(null)
    apiFetch('/ai/suggest-trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ allow_loss: allowLoss }),
    })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail ?? r.statusText)))
      .then(d => { setResult(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }

  return (
    <div>
      {!marketOpen && (
        <div style={{
          background: '#1a1a2a', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', padding: '8px 12px', marginBottom: 12,
          fontSize: 11, color: 'var(--text-muted)',
        }}>
          Market closed{closedRange ? ` (${closedRange})` : ''} — suggestions use last cached context.
        </div>
      )}
      {/* controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button onClick={fetchSuggestions} disabled={loading} style={{
          background: loading ? 'var(--surface)' : '#1a3a2a',
          border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          color: loading ? 'var(--text-muted)' : 'var(--green)',
          padding: '5px 14px', fontSize: 12, cursor: loading ? 'default' : 'pointer', fontWeight: 600,
        }}>
          {loading ? 'Analyzing…' : 'Get Suggestions'}
        </button>
        <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={allowLoss} onChange={e => setAllowLoss(e.target.checked)} />
          Allow loss trades
        </label>
      </div>

      {error && <p className="error">Error: {error}</p>}

      {result && (
        <>
          {/* guardrail banner */}
          {result.any_guardrail_triggered && (
            <div style={{
              background: '#3a1a1a', border: '1px solid #f85149', borderRadius: 'var(--radius)',
              padding: '8px 12px', marginBottom: 12, fontSize: 12, color: '#f85149',
            }}>
              ⚠ Guardrail triggered — {result.risk_note}
            </div>
          )}

          {/* context strip */}
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12, display: 'flex', gap: 16 }}>
            <span>Goal <strong style={{ color: 'var(--text)' }}>${result.goal}</strong></span>
            <span>Mode <strong style={{ color: 'var(--text)' }}>{result.profit_mode}</strong></span>
            <span>Scope <strong style={{ color: 'var(--text)' }}>{result.trade_scope}</strong></span>
          </div>

          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14, lineHeight: 1.6 }}>
            {result.market_conditions}
          </p>

          {result.suggestions.length === 0 && (
            <p className="status">No suggestions — {result.risk_note}</p>
          )}

          {result.suggestions.map(trade => (
            <SuggestionCard
              key={trade.ticker + trade.direction}
              trade={trade}
              isRecommended={result.recommended?.ticker === trade.ticker && result.recommended?.direction === trade.direction}
              allowLoss={allowLoss}
            />
          ))}

          {!result.any_guardrail_triggered && result.risk_note && (
            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{result.risk_note}</p>
          )}
        </>
      )}
    </div>
  )
}

function ChatTab() {
  const [messages, setMessages] = useState([])
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const bottomRef               = useRef(null)

  function send() {
    const text = input.trim()
    if (!text || loading) return
    const next = [...messages, { role: 'user', text }]
    setMessages(next)
    setInput('')
    setLoading(true)
    apiFetch('/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail ?? r.statusText)))
      .then(d => {
        setMessages([...next, { role: 'assistant', text: d.reply }])
        setLoading(false)
        setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
      })
      .catch(e => {
        setMessages([...next, { role: 'error', text: String(e) }])
        setLoading(false)
      })
  }

  return (
    <div>
      {/* message history */}
      <div style={{ minHeight: 80, maxHeight: 420, overflowY: 'auto', marginBottom: 12 }}>
        {messages.length === 0 && (
          <p className="status">Ask anything about today's market, your positions, or trade setups.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{
            marginBottom: 12,
            textAlign: m.role === 'user' ? 'right' : 'left',
          }}>
            <span style={{
              display: 'inline-block', maxWidth: '85%', padding: '7px 12px',
              borderRadius: 8, fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap',
              background: m.role === 'user' ? '#1c2d3d' : m.role === 'error' ? '#3a1a1a' : 'var(--surface)',
              color: m.role === 'error' ? 'var(--red)' : 'var(--text)',
              textAlign: 'left',
            }}>
              {m.text}
            </span>
          </div>
        ))}
        {loading && (
          <div style={{ marginBottom: 12 }}>
            <span style={{ display: 'inline-block', padding: '7px 12px', borderRadius: 8, background: 'var(--surface)', fontSize: 13, color: 'var(--text-muted)' }}>
              Thinking…
            </span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* input */}
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Ask about today's setups, risk, positions…"
          disabled={loading}
          style={{
            flex: 1, background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', color: 'var(--text)', fontSize: 13,
            padding: '7px 12px', outline: 'none',
          }}
        />
        <button onClick={send} disabled={loading || !input.trim()} style={{
          background: loading || !input.trim() ? 'var(--surface)' : '#1c2d3d',
          border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          color: loading || !input.trim() ? 'var(--text-muted)' : 'var(--blue)',
          padding: '7px 14px', fontSize: 12, cursor: loading || !input.trim() ? 'default' : 'pointer',
          fontWeight: 600,
        }}>
          Send
        </button>
      </div>
    </div>
  )
}

export default function ChatPanel() {
  const [tab, setTab]           = useState('suggest')
  const [expanded, setExpanded] = useState(true)

  return (
    <div className="panel">
      <div className="panel-header" style={{ marginBottom: expanded ? 16 : 0 }}>
        <button onClick={() => setExpanded(e => !e)} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6, padding: 0,
        }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{expanded ? '▼' : '▶'}</span>
          <h2 style={{ margin: 0 }}>AI Assistant</h2>
        </button>

        {expanded && (
          <div style={{ display: 'flex', gap: 4 }}>
            {['suggest', 'chat'].map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                background: tab === t ? 'var(--surface)' : 'none',
                border: `1px solid ${tab === t ? 'var(--border)' : 'transparent'}`,
                borderRadius: 'var(--radius)', color: tab === t ? 'var(--text)' : 'var(--text-muted)',
                padding: '3px 10px', fontSize: 11, cursor: 'pointer', fontWeight: tab === t ? 600 : 400,
              }}>
                {t === 'suggest' ? 'Suggestions' : 'Chat'}
              </button>
            ))}
          </div>
        )}
      </div>

      {expanded && (tab === 'suggest' ? <SuggestTab /> : <ChatTab />)}
    </div>
  )
}
