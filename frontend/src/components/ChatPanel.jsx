import { useRef, useState } from 'react'
import { Badge, Button, Group, Paper, ScrollArea, SimpleGrid, Text, TextInput } from '@mantine/core'
import { useMarketStatus } from '../utils/market'
import { apiFetch } from '../utils/api'

function dirBadge(direction) {
  return <Badge color={direction === 'long' ? 'green' : 'red'} size="xs" radius="xl" variant="light">{direction.toUpperCase()}</Badge>
}

function optionTypeBadge(optionType) {
  return <Badge color={optionType === 'call' ? 'green' : 'red'} size="xs" radius="xl" variant="light">{optionType.toUpperCase()}</Badge>
}

function confBadge(confidence) {
  const color = confidence === 'high' ? 'green' : confidence === 'medium' ? 'yellow' : 'red'
  return <Badge color={color} size="xs" radius="xl" variant="light">{confidence.toUpperCase()}</Badge>
}

function SuggestionCard({ trade, isRecommended, allowLoss }) {
  const [rhOpen, setRhOpen]         = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted]   = useState(false)
  const [submitErr, setSubmitErr]   = useState(null)
  const pnlColor = (trade.current_unrealized_pnl ?? 0) >= 0 ? 'green' : 'red'
  const isOption = trade.instrument_type === 'option'
  const totalCost = isOption ? trade.entry_price * trade.shares * (trade.multiplier ?? 100) : null

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
    <Paper
      p="sm"
      radius="sm"
      style={{
        border: `1px solid ${isRecommended ? 'var(--green)' : 'var(--border)'}`,
        background: isRecommended ? '#0d1f12' : 'var(--bg)',
        marginBottom: 12,
      }}
    >
      {/* header */}
      <Group gap="xs" mb="xs" wrap="wrap">
        <Text fw={700} size="sm" ff="mono">{trade.ticker}</Text>
        {isOption ? optionTypeBadge(trade.option_type) : dirBadge(trade.direction)}
        {confBadge(trade.confidence)}
        <Text size="xs" c="dimmed" ml="auto">{trade.trade_type.replace(/_/g, ' ')}</Text>
        {isRecommended && <Text size="xs" fw={700} c="green">★ RECOMMENDED</Text>}
      </Group>

      {/* option-specific: strike, expiration, DTE */}
      {isOption && (
        <Group gap="md" mb="xs">
          <Text size="xs" c="dimmed">
            Strike <Text span fw={700} c="var(--text)" ff="mono">${trade.strike_price.toFixed(2)}</Text>
          </Text>
          <Text size="xs" c="dimmed">
            Exp <Text span fw={700} c="var(--text)" ff="mono">{trade.expiration_date}</Text>
          </Text>
          <Text size="xs" c="dimmed">
            DTE <Text span fw={700} c="var(--text)" ff="mono">{trade.days_to_expiration}</Text>
          </Text>
        </Group>
      )}

      {/* price grid */}
      <SimpleGrid cols={{ base: 2, sm: 3 }} mb="xs">
        {[
          [isOption ? 'Premium' : 'Entry', `$${trade.entry_price.toFixed(2)}`],
          ['Target',    `$${trade.target_price.toFixed(2)}`],
          ['Stop',      `$${trade.stop_loss.toFixed(2)}`],
          [isOption ? 'Contracts' : 'Shares', trade.shares],
          ['Exp. Gain', `+$${trade.expected_gain.toFixed(0)}`],
          ['Max Loss',  `-$${trade.max_loss.toFixed(0)}`],
        ].map(([label, val]) => (
          <Paper key={label} p="xs" radius="xs" style={{ background: 'var(--surface)' }}>
            <Text size="xs" c="dimmed" mb={2}>{label}</Text>
            <Text size="xs" fw={600} ff="mono">{val}</Text>
          </Paper>
        ))}
      </SimpleGrid>

      {/* option-specific: breakeven, delta, total cost */}
      {isOption && (
        <Group gap="md" mb="xs">
          <Text size="xs" c="dimmed">
            Breakeven <Text span fw={700} c="var(--text)" ff="mono">${trade.breakeven_price.toFixed(2)}</Text>
          </Text>
          {trade.delta_at_entry != null && (
            <Text size="xs" c="dimmed">
              Delta <Text span fw={700} c="var(--text)" ff="mono">{trade.delta_at_entry.toFixed(2)}</Text>
            </Text>
          )}
          <Text size="xs" c="dimmed">
            Total cost <Text span fw={700} c="var(--text)" ff="mono">${totalCost.toFixed(0)}</Text>
            <Text span c="dimmed"> ({trade.shares} × ${trade.entry_price.toFixed(2)} × {trade.multiplier ?? 100})</Text>
          </Text>
        </Group>
      )}

      {/* R/R + holding context */}
      <Group gap="md" mb="xs">
        <Text size="xs" c="dimmed">
          R/R <Text span fw={700} c="var(--text)">{trade.reward_risk_ratio.toFixed(2)}</Text>
        </Text>
        {trade.ml_probability != null && (
          <Text size="xs" c="dimmed">
            Hit prob{' '}
            <Text
              span
              fw={700}
              ff="mono"
              c={trade.ml_probability >= 0.5 ? 'green' : trade.ml_probability >= 0.3 ? 'yellow' : 'red'}
            >
              {(trade.ml_probability * 100).toFixed(0)}%
            </Text>
          </Text>
        )}
        {trade.stop_probability != null && (
          <Text size="xs" c="dimmed">
            Stop prob{' '}
            <Text
              span
              fw={700}
              ff="mono"
              c={trade.stop_probability >= 0.5 ? 'red' : trade.stop_probability >= 0.3 ? 'yellow' : 'green'}
            >
              {(trade.stop_probability * 100).toFixed(0)}%
            </Text>
          </Text>
        )}
        {trade.expected_value != null && (
          <Text size="xs" c="dimmed" title={trade.ev_calibration_note ?? undefined}>
            EV{' '}
            <Text span fw={700} ff="mono" c={trade.expected_value >= 0 ? 'green' : 'red'}>
              {trade.expected_value >= 0 ? '+' : '-'}${Math.abs(trade.expected_value).toFixed(0)}
            </Text>
          </Text>
        )}
        {trade.uses_existing_holding && trade.cost_basis != null && (
          <Text size="xs" c="dimmed">
            Cost basis <Text span fw={700} c="var(--text)" ff="mono">${trade.cost_basis.toFixed(2)}</Text>
          </Text>
        )}
        {trade.current_unrealized_pnl != null && (
          <Text size="xs" c="dimmed">
            Unrealized P&L <Text span fw={700} c={pnlColor} ff="mono">${trade.current_unrealized_pnl.toFixed(0)}</Text>
          </Text>
        )}
      </Group>

      {/* rationale */}
      <Text size="xs" c="dimmed" mb="xs" style={{ lineHeight: 1.6 }}>
        {trade.rationale}
      </Text>

      {/* paper trade action */}
      <Group gap="xs" mb="xs">
        <Button
          size="xs"
          variant={submitted ? 'light' : 'outline'}
          color={submitted ? 'green' : 'blue'}
          disabled={submitting || submitted}
          onClick={paperTrade}
        >
          {submitted ? '✓ Paper Trade Logged' : submitting ? 'Submitting…' : 'Paper Trade'}
        </Button>
        {submitErr && <Text size="xs" c="red">{submitErr}</Text>}
      </Group>

      {/* robinhood instructions */}
      <Button
        variant="subtle"
        size="xs"
        fullWidth
        justify="left"
        onClick={() => setRhOpen(o => !o)}
        style={{ textAlign: 'left' }}
      >
        {rhOpen ? '▼' : '▶'} Robinhood Instructions
      </Button>
      {rhOpen && (
        <Text
          size="xs"
          style={{ lineHeight: 1.7, marginTop: 8, padding: '8px 10px', background: 'var(--surface)', borderRadius: 4, whiteSpace: 'pre-wrap' }}
        >
          {trade.robinhood_instructions}
        </Text>
      )}
    </Paper>
  )
}

function SuggestTab() {
  const [result, setResult]       = useState(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)
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
        <Paper p="xs" mb="xs" radius="xs" style={{ background: '#1a1a2a', border: '1px solid var(--border)' }}>
          <Text size="xs" c="dimmed">
            Market closed{closedRange ? ` (${closedRange})` : ''} — suggestions use last cached context.
          </Text>
        </Paper>
      )}

      <Group gap="sm" mb="md">
        <Button
          size="xs"
          variant="light"
          color="green"
          disabled={loading}
          onClick={fetchSuggestions}
        >
          {loading ? 'Analyzing…' : 'Get Suggestions'}
        </Button>
        <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={allowLoss} onChange={e => setAllowLoss(e.target.checked)} />
          Allow loss trades
        </label>
      </Group>

      {error && <Text c="red" size="sm" py="xs">Error: {error}</Text>}

      {result && (
        <>
          {result.any_guardrail_triggered && (
            <Paper p="xs" mb="xs" radius="xs" style={{ background: '#3a1a1a', border: '1px solid var(--red)' }}>
              <Text size="xs" c="red">⚠ Guardrail triggered — {result.risk_note}</Text>
            </Paper>
          )}

          <Group gap="md" mb="xs">
            <Text size="xs" c="dimmed">Goal <Text span fw={700} c="var(--text)">${result.goal}</Text></Text>
            <Text size="xs" c="dimmed">Mode <Text span fw={700} c="var(--text)">{result.profit_mode}</Text></Text>
            <Text size="xs" c="dimmed">Scope <Text span fw={700} c="var(--text)">{result.trade_scope}</Text></Text>
          </Group>

          <Text size="xs" c="dimmed" mb="sm" style={{ lineHeight: 1.6 }}>{result.market_conditions}</Text>

          {result.suggestions.length === 0 && (
            <Text c="dimmed" size="sm" py="xs">No suggestions — {result.risk_note}</Text>
          )}

          {result.suggestions.map(trade => {
            const tradeKey = trade.option_symbol ?? (trade.ticker + trade.direction)
            const recommendedKey = result.recommended?.option_symbol
              ?? (result.recommended ? result.recommended.ticker + result.recommended.direction : null)
            return (
              <SuggestionCard
                key={tradeKey}
                trade={trade}
                isRecommended={recommendedKey === tradeKey}
                allowLoss={allowLoss}
              />
            )
          })}

          {!result.any_guardrail_triggered && result.risk_note && (
            <Text size="xs" c="dimmed" mt="xs">{result.risk_note}</Text>
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
      <ScrollArea h={420} mb="xs">
        {messages.length === 0 && (
          <Text c="dimmed" size="sm" py="xs">
            Ask anything about today's market, your positions, or trade setups.
          </Text>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 12, textAlign: m.role === 'user' ? 'right' : 'left' }}>
            <Text
              size="sm"
              span
              style={{
                display: 'inline-block', maxWidth: '85%', padding: '7px 12px',
                borderRadius: 8, lineHeight: 1.6, whiteSpace: 'pre-wrap',
                background: m.role === 'user' ? '#1c2d3d' : m.role === 'error' ? '#3a1a1a' : 'var(--surface)',
                color: m.role === 'error' ? 'var(--red)' : 'var(--text)',
                textAlign: 'left',
              }}
            >
              {m.text}
            </Text>
          </div>
        ))}
        {loading && (
          <div style={{ marginBottom: 12 }}>
            <Text size="sm" span style={{ display: 'inline-block', padding: '7px 12px', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-muted)' }}>
              Thinking…
            </Text>
          </div>
        )}
        <div ref={bottomRef} />
      </ScrollArea>

      <Group gap="xs">
        <TextInput
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Ask about today's setups, risk, positions…"
          disabled={loading}
          size="sm"
          style={{ flex: 1 }}
        />
        <Button
          size="sm"
          variant="light"
          color="blue"
          disabled={loading || !input.trim()}
          onClick={send}
        >
          Send
        </Button>
      </Group>
    </div>
  )
}

export default function ChatPanel() {
  const [tab, setTab]           = useState('suggest')
  const [expanded, setExpanded] = useState(true)

  return (
    <Paper p="md">
      <Group justify="space-between" mb={expanded ? 'md' : 0}>
        <button
          onClick={() => setExpanded(e => !e)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}
        >
          <Text size="xs" c="dimmed">{expanded ? '▼' : '▶'}</Text>
          <Text size="xs" fw={600} tt="uppercase" c="dimmed">AI Assistant</Text>
        </button>

        {expanded && (
          <Group gap={4}>
            {['suggest', 'chat'].map(t => (
              <Button
                key={t}
                size="xs"
                variant={tab === t ? 'light' : 'subtle'}
                onClick={() => setTab(t)}
              >
                {t === 'suggest' ? 'Suggestions' : 'Chat'}
              </Button>
            ))}
          </Group>
        )}
      </Group>

      {expanded && (tab === 'suggest' ? <SuggestTab /> : <ChatTab />)}
    </Paper>
  )
}
