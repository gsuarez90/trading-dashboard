import { useEffect, useState } from 'react'
import { Button, Group, Paper, Text } from '@mantine/core'
import { useMarketStatus } from '../utils/market'
import { apiFetch } from '../utils/api'

export default function DailySummaryPanel() {
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [expanded, setExpanded] = useState(true)

  function fetchBriefing() {
    setLoading(true)
    setError(null)
    apiFetch('/ai/briefing')
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }

  useEffect(() => { fetchBriefing() }, [])

  const { isTodayTradingDay, nextOpenDate } = useMarketStatus()

  const minsLeft = data?.minutes_remaining
  const marketOpen = minsLeft != null && minsLeft > 0

  // Today's ET date in YYYY-MM-DD — same format the backend returns in data.date
  const todayET = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' })
  // Stale: market is open but the briefing is dated before today (9:30–9:32 window)
  const briefingIsStale = !!(data?.briefing && data.date && marketOpen && data.date < todayET)
  // Pending: market is open but today's briefing hasn't been written yet (9:32–9:35 window)
  const briefingPending = !!(data && !data.briefing && marketOpen)

  return (
    <Paper p="md">
      <Group justify="space-between" mb={expanded ? 'xs' : 0}>
        <button
          onClick={() => setExpanded(e => !e)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}
        >
          <Text size="xs" c="dimmed" lh={1}>{expanded ? '▼' : '▶'}</Text>
          <Text size="xs" fw={600} tt="uppercase" c="dimmed">Morning Briefing</Text>
        </button>

        <Group gap="xs">
          {data && (
            <Text size="xs" c="dimmed" ff="mono">
              {data.date}
              {minsLeft != null && (
                <Text span c={marketOpen ? 'green' : 'dimmed'} ml={8}>
                  {marketOpen ? `${minsLeft}m remaining` : 'Market closed'}
                </Text>
              )}
            </Text>
          )}
          <Button variant="subtle" size="xs" onClick={fetchBriefing} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </Group>
      </Group>

      {expanded && (
        <>
          {error && <Text c="red" size="sm" py="xs">Error: {error}</Text>}
          {!error && data && data.briefing && marketOpen && (
            <>
              {briefingIsStale && (
                <Text size="xs" c="orange" mb="xs">
                  Showing {data.date} briefing — today's generating now.
                </Text>
              )}
              <Text size="sm" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                {data.briefing}
              </Text>
            </>
          )}
          {!error && briefingPending && (
            <Text c="dimmed" size="sm" py="xs">
              Today's briefing is generating — refresh in a few minutes.
            </Text>
          )}
          {!error && data && !data.briefing && !briefingPending && (
            <Text c="dimmed" size="sm" py="xs">
              {isTodayTradingDay
                ? 'Market closed — new briefing at market open (~9:35 AM ET).'
                : `Market closed — next briefing ${nextOpenDate}, ~9:35 AM ET.`}
            </Text>
          )}
          {loading && <Text c="dimmed" size="sm" py="xs">Loading…</Text>}
        </>
      )}
    </Paper>
  )
}
