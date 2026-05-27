import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, Group, Paper, Progress, SimpleGrid, Text, TextInput } from '@mantine/core'
import { apiFetch } from '../utils/api'

const DIR_STYLE = {
  long:  { color: 'green' },
  short: { color: 'red' },
}

const REASON_LABEL = {
  target_hit:  'Target hit',
  stop_hit:    'Stop hit',
  manual:      'Manual',
  eod_close:   'EOD close',
  kill_switch: 'Kill switch',
  expired:     'Expired (unfilled)',
  cancelled:   'Cancelled',
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

function SummaryBar({ summary }) {
  if (!summary) return null
  const pct = summary.goal > 0 ? Math.min(100, (summary.realized_pnl / summary.goal) * 100) : 0
  const pnlColor = summary.realized_pnl >= 0 ? 'green' : 'red'

  return (
    <Paper p="xs" mb="sm" radius="xs">
      <Group gap="lg" mb="xs" wrap="wrap">
        <Text size="xs" c="dimmed">
          Realized P&L{' '}
          <Text span fw={700} size="sm" c={pnlColor} ff="mono">{fmt(summary.realized_pnl)}</Text>
        </Text>
        <Text size="xs" c="dimmed">
          Goal <Text span fw={600} ff="mono">${summary.goal}</Text>
        </Text>
        <Text size="xs" c="dimmed">
          Open <Text span fw={600}>{summary.open_positions}</Text>
        </Text>
        {summary.cumulative_pnl != null && (
          <Text size="xs" c="dimmed">
            All-Time <Text span fw={600} ff="mono" c={summary.cumulative_pnl >= 0 ? 'green' : 'red'}>{fmt(summary.cumulative_pnl)}</Text>
          </Text>
        )}
        {summary.goal_hit && (
          <Badge color="green" size="xs" radius="xl" variant="light">
            GOAL HIT{summary.goal_hit_time ? ` @ ${fmtTime(summary.goal_hit_time)}` : ''}
          </Badge>
        )}
        <Text size="xs" c="dimmed" ml="auto">{summary.settlement_note}</Text>
      </Group>
      <Progress
        value={Math.max(0, pct)}
        color={summary.goal_hit ? 'green' : 'yellow'}
        size="xs"
        radius="xs"
      />
    </Paper>
  )
}

function OpenRow({ trade, onClose }) {
  const [open, setOpen]   = useState(false)
  const [price, setPrice] = useState('')
  const [busy, setBusy]   = useState(false)
  const [err, setErr]     = useState(null)
  const dirColor = DIR_STYLE[trade.direction]?.color ?? 'green'

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
    <Paper p="xs" mb="xs" radius="xs">
      <Group gap="xs" wrap="wrap">
        <Text fw={700} size="sm" ff="mono" style={{ minWidth: 52 }}>{trade.ticker}</Text>
        <Badge color={dirColor} size="xs" radius="xl" variant="light">{trade.direction.toUpperCase()}</Badge>
        <Text size="xs" c="dimmed">
          {trade.shares} sh @ <Text span ff="mono">${trade.entry_price.toFixed(2)}</Text>
        </Text>
        <Text size="xs" c="dimmed">
          T <Text span ff="mono" c="green">${trade.target_price.toFixed(2)}</Text>
          {' / '}
          S <Text span ff="mono" c="red">${trade.stop_loss.toFixed(2)}</Text>
        </Text>
        <Text size="xs" c="dimmed" ml="auto">{fmtTime(trade.entry_time)}</Text>
        <Button
          size="xs"
          variant={open ? 'light' : 'subtle'}
          onClick={() => setOpen(o => !o)}
        >
          {open ? 'Cancel' : 'Close'}
        </Button>
      </Group>

      {open && (
        <Group gap="xs" mt="xs">
          <TextInput
            size="xs"
            type="number"
            step="0.01"
            placeholder="Exit price"
            value={price}
            onChange={e => setPrice(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()}
            style={{ width: 120 }}
          />
          <Button size="xs" variant="light" color="blue" disabled={busy} onClick={submit}>
            {busy ? 'Closing…' : 'Confirm'}
          </Button>
          {err && <Text size="xs" c="red">{err}</Text>}
        </Group>
      )}
    </Paper>
  )
}

function PendingRow({ trade, onCancel }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr]   = useState(null)
  const dirColor = DIR_STYLE[trade.direction]?.color ?? 'green'

  function cancel() {
    setBusy(true)
    setErr(null)
    apiFetch(`/paper-trades/${trade.trade_id}/cancel`, { method: 'POST' })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail ?? r.statusText)))
      .then(() => { setBusy(false); onCancel() })
      .catch(e => { setErr(String(e)); setBusy(false) })
  }

  return (
    <Paper p="xs" mb="xs" radius="xs" style={{ opacity: 0.85 }}>
      <Group gap="xs" wrap="wrap">
        <Text fw={700} size="sm" ff="mono" style={{ minWidth: 52 }}>{trade.ticker}</Text>
        <Badge color={dirColor} size="xs" radius="xl" variant="light">{trade.direction.toUpperCase()}</Badge>
        <Text size="xs" c="dimmed">{trade.shares} sh</Text>
        <Text size="xs" c="dimmed">
          Limit <Text span ff="mono">${(trade.limit_price ?? trade.entry_price).toFixed(2)}</Text>
        </Text>
        <Text size="xs" c="dimmed">
          T <Text span ff="mono" c="green">${trade.target_price.toFixed(2)}</Text>
          {' / '}
          S <Text span ff="mono" c="red">${trade.stop_loss.toFixed(2)}</Text>
        </Text>
        <Badge color="yellow" size="xs" radius="xl" variant="light" ml="auto">PENDING</Badge>
        <Text size="xs" c="dimmed">{fmtTime(trade.pending_since)}</Text>
        <Button size="xs" variant="subtle" color="red" disabled={busy} onClick={cancel}>
          {busy ? 'Cancelling…' : 'Cancel'}
        </Button>
      </Group>
      {err && <Text size="xs" c="red" mt={4}>{err}</Text>}
    </Paper>
  )
}

function HistoryRow({ trade }) {
  const pnl = trade.realized_pnl ?? 0
  const dirColor = DIR_STYLE[trade.direction]?.color ?? 'green'

  return (
    <Group
      gap="xs"
      wrap="wrap"
      py="xs"
      style={{ borderBottom: '1px solid var(--border)', fontSize: 12 }}
    >
      <Text fw={700} ff="mono" size="xs" style={{ minWidth: 52 }}>{trade.ticker}</Text>
      <Badge color={dirColor} size="xs" radius="xl" variant="light">{trade.direction.toUpperCase()}</Badge>
      <Text size="xs" c="dimmed">{trade.shares} sh</Text>
      <Text size="xs" c="dimmed" ff="mono">
        ${trade.entry_price.toFixed(2)} → {trade.exit_price != null ? `$${trade.exit_price.toFixed(2)}` : '—'}
      </Text>
      <Text size="xs" c="dimmed">{REASON_LABEL[trade.close_reason] ?? trade.close_reason ?? '—'}</Text>
      <Text size="xs" fw={700} ff="mono" c={pnl >= 0 ? 'green' : 'red'} ml="auto">{fmt(pnl)}</Text>
      <Text size="xs" c="dimmed">{fmtTime(trade.exit_time)}</Text>
    </Group>
  )
}

function OpenTab({ trades, onClose }) {
  const open = trades.filter(t => t.status === 'open')
  if (open.length === 0) return <Text c="dimmed" size="sm" py="xs">No open positions today.</Text>
  return open.map(t => <OpenRow key={t.trade_id} trade={t} onClose={onClose} />)
}

function PendingTab({ pending, onCancel }) {
  if (pending.length === 0) return <Text c="dimmed" size="sm" py="xs">No pending orders today.</Text>
  return pending.map(t => <PendingRow key={t.trade_id} trade={t} onCancel={onCancel} />)
}

function HistoryTab({ trades }) {
  const closed = trades.filter(t => t.status !== 'open' && t.status !== 'pending')
  if (closed.length === 0) return <Text c="dimmed" size="sm" py="xs">No closed trades today.</Text>
  return <div>{closed.map(t => <HistoryRow key={t.trade_id} trade={t} />)}</div>
}

function SummaryTab({ summary }) {
  if (!summary) return <Text c="dimmed" size="sm" py="xs">Loading…</Text>
  const pnlColor = summary.realized_pnl >= 0 ? 'green' : 'red'

  return (
    <SimpleGrid cols={{ base: 2 }}>
      {[
        ['Date',           summary.date,          null],
        ['Realized P&L',   fmt(summary.realized_pnl), pnlColor],
        ['Daily Goal',     `$${summary.goal}`,    null],
        ['Open Positions', summary.open_positions, null],
        ['Goal Hit',       summary.goal_hit ? `Yes @ ${fmtTime(summary.goal_hit_time)}` : 'Not yet', null],
        ['Mode',           summary.trading_mode,  null],
        ['All-Time P&L',   fmt(summary.cumulative_pnl ?? 0), (summary.cumulative_pnl ?? 0) >= 0 ? 'green' : 'red'],
      ].map(([label, val, color]) => (
        <Paper key={label} p="xs" radius="xs">
          <Text size="xs" c="dimmed" mb={3}>{label}</Text>
          <Text size="sm" fw={600} ff="mono" c={color ?? undefined}>{val}</Text>
        </Paper>
      ))}
      <Paper p="xs" radius="xs" style={{ gridColumn: '1 / -1' }}>
        <Text size="xs" c="dimmed" mb={3}>Settlement</Text>
        <Text size="xs">{summary.settlement_note}</Text>
      </Paper>
    </SimpleGrid>
  )
}

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

  useEffect(() => { load() }, [load])

  function toggleExpand() {
    setExpanded(e => !e)
  }

  const TABS = ['open', 'pending', 'history', 'summary']

  return (
    <Paper p="md">
      <Group justify="space-between" mb={expanded ? 'sm' : 0}>
        <button
          onClick={toggleExpand}
          style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}
        >
          <Text size="xs" c="dimmed">{expanded ? '▼' : '▶'}</Text>
          <Text size="xs" fw={600} tt="uppercase" c="dimmed">Paper Trading</Text>
        </button>

        {expanded && (
          <Group gap="xs" wrap="wrap">
            <Group gap={4}>
              {TABS.map(t => {
                const count =
                  t === 'open'    ? trades.filter(x => x.status === 'open').length :
                  t === 'pending' ? pending.length : 0
                const label = t.charAt(0).toUpperCase() + t.slice(1)
                return (
                  <Button
                    key={t}
                    size="xs"
                    variant={tab === t ? 'light' : 'subtle'}
                    onClick={() => setTab(t)}
                  >
                    {count > 0 ? `${label} (${count})` : label}
                  </Button>
                )
              })}
            </Group>
            <Button variant="subtle" size="xs" onClick={load} disabled={loading}>
              {loading ? 'Loading…' : 'Refresh'}
            </Button>
          </Group>
        )}
      </Group>

      {expanded && (
        <>
          {error && <Text c="red" size="sm" py="xs">Error: {error}</Text>}
          {!error && !loading && (
            <>
              <SummaryBar summary={summary} />
              {tab === 'open'    && <OpenTab    trades={trades} onClose={load} />}
              {tab === 'pending' && <PendingTab pending={pending} onCancel={load} />}
              {tab === 'history' && <HistoryTab trades={trades} />}
              {tab === 'summary' && <SummaryTab summary={summary} />}
            </>
          )}
          {loading && <Text c="dimmed" size="sm" py="xs">Loading…</Text>}
        </>
      )}
    </Paper>
  )
}
