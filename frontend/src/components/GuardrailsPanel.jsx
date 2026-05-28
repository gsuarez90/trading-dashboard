import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, Group, Paper, SimpleGrid, Text } from '@mantine/core'
import { apiFetch } from '../utils/api'

const RULE_LABELS = {
  daily_loss_limit:      'Daily Loss Limit',
  position_size_cap:     'Position Size Cap',
  cost_basis_protection: 'Cost Basis Protection',
  reward_risk_minimum:   'Reward/Risk Minimum',
  daily_trade_limit:     'Daily Trade Limit',
  market_hours_lock:     'Market Hours Lock',
  intraday_60min_cutoff: 'Intraday 60-Min Cutoff',
  buying_power_check:    'Buying Power Check',
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function StatusCards({ status }) {
  if (!status) return null
  const loss   = status.daily_loss_limit
  const trades = status.daily_trade_limit
  const hours  = status.market_hours

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
      sub: trades.pdt_exempt ? `${trades.trades_today} trades (Unlimited)` : `${trades.trades_today} of ${trades.limit} trades`,
      ok: !trades.triggered,
    },
  ]

  return (
    <SimpleGrid cols={{ base: 2, sm: 4 }} mb="md">
      {cards.map(({ label, value, sub, ok }) => (
        <Paper
          key={label}
          p="xs"
          radius="xs"
          style={{ borderLeft: `3px solid ${ok ? 'var(--green)' : 'var(--red)'}` }}
        >
          <Text size="xs" c="dimmed" mb={4}>{label}</Text>
          <Text size="sm" fw={700} ff="mono" c={ok ? 'green' : 'red'}>{value}</Text>
          <Text size="xs" c="dimmed" mt={3}>{sub}</Text>
        </Paper>
      ))}
    </SimpleGrid>
  )
}

function EventsLog({ events }) {
  if (events.length === 0) {
    return <Text c="dimmed" size="sm" py="xs">No guardrail triggers today.</Text>
  }

  return (
    <div>
      {events.map(e => (
        <Paper
          key={e.trade_id}
          p="xs"
          radius="xs"
          mb="xs"
          style={{ borderLeft: '3px solid var(--red)' }}
        >
          <Group justify="space-between" mb="xs">
            <Text fw={700} size="sm" ff="mono">{e.ticker}</Text>
            <Text size="xs" c="dimmed">{fmtTime(e.timestamp)}</Text>
          </Group>
          <Group gap={4} mb="xs" wrap="wrap">
            {(e.rules_triggered || []).map(rule => (
              <Badge key={rule} color="red" size="xs" radius="xl" variant="light">
                {RULE_LABELS[rule] ?? rule}
              </Badge>
            ))}
          </Group>
          <Text size="xs" c="dimmed">{(e.messages || []).join(' · ')}</Text>
        </Paper>
      ))}
    </div>
  )
}

function KillSwitch() {
  const [busy, setBusy]       = useState(false)
  const [result, setResult]   = useState(null)
  const [error, setError]     = useState(null)
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
    <Paper
      p="xs"
      mt="md"
      radius="xs"
      style={{ background: '#1e0a0a', border: '1px solid #5a1a1a' }}
    >
      <Group gap="xs" wrap="wrap">
        <Text size="xs" fw={600} c="red">Kill Switch</Text>
        <Text size="xs" c="dimmed" style={{ flex: 1 }}>
          Closes all open paper trades. Flags live trades for manual close in Robinhood.
        </Text>
        {result && (
          <Text size="xs" c="green">
            Done — {result.paper_trades_closed} paper closed, {result.live_trades_flagged} live flagged
          </Text>
        )}
        {error && <Text size="xs" c="red">{error}</Text>}
        <Button
          size="xs"
          variant={confirm ? 'filled' : 'outline'}
          color="red"
          disabled={busy}
          onClick={fire}
        >
          {busy ? 'Running…' : confirm ? 'Confirm — Close All' : 'Activate'}
        </Button>
        {confirm && !busy && (
          <Button size="xs" variant="subtle" onClick={() => setConfirm(false)}>Cancel</Button>
        )}
      </Group>
    </Paper>
  )
}

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

  useEffect(() => {
    load()
    setLoaded(true)
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, 60_000)
    return () => clearInterval(id)
  }, [load])

  return (
    <Paper p="md">
      <Group justify="space-between" mb={expanded ? 'sm' : 0}>
        <button
          onClick={toggleExpand}
          style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}
        >
          <Text size="xs" c="dimmed">{expanded ? '▼' : '▶'}</Text>
          <Text size="xs" fw={600} tt="uppercase" c="dimmed">
            Guardrails
            {events.length > 0 && (
              <Badge color="red" size="xs" radius="xl" variant="light" ml="xs">
                {events.length} trigger{events.length !== 1 ? 's' : ''} today
              </Badge>
            )}
          </Text>
        </button>

        {expanded && (
          <Button variant="subtle" size="xs" onClick={load} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        )}
      </Group>

      {expanded && (
        <>
          {error && <Text c="red" size="sm" py="xs">Error: {error}</Text>}
          {!error && !loading && (
            <>
              <StatusCards status={status} />
              <Text size="xs" fw={600} c="dimmed" mb="xs">Today's Triggers</Text>
              <EventsLog events={events} />
              <KillSwitch />
            </>
          )}
          {loading && <Text c="dimmed" size="sm" py="xs">Loading…</Text>}
        </>
      )}
    </Paper>
  )
}
