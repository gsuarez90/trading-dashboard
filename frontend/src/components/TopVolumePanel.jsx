import { useCallback, useEffect, useState } from 'react'
import { Group, Paper, Stack, Text } from '@mantine/core'
import { BarChart } from '@mantine/charts'
import { useMarketStatus } from '../utils/market'
import { apiFetch } from '../utils/api'

const POLL_INTERVAL = 60_000
const TOP_N = 5

function formatVolume(v) {
  if (v >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(1)}B`
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`
  return `${v}`
}

// earningsByTicker: undefined key = still loading, [] = no data for this ticker (ETFs, thin coverage)
function EarningsTooltip({ active, payload, label, earningsByTicker }) {
  if (!active || !payload?.length) return null

  const volume = payload[0]?.value
  const earnings = earningsByTicker[label]

  return (
    <Paper p="xs" withBorder shadow="md" style={{ fontSize: 12 }}>
      <Text size="xs" fw={700}>{label}</Text>
      <Text size="xs" c="dimmed" mb={6}>volume: {volume?.toLocaleString()}</Text>

      <Text size="xs" fw={600} tt="uppercase" c="dimmed" mb={4}>Quarterly EPS — Est vs Act</Text>

      {earnings === undefined && (
        <Text size="xs" c="dimmed">Loading earnings…</Text>
      )}
      {earnings?.length === 0 && (
        <Text size="xs" c="dimmed">No earnings data</Text>
      )}
      {earnings?.length > 0 && (
        <Stack gap={2}>
          {earnings.map(q => (
            <Text key={q.period} size="xs" ff="mono" c={q.actual >= q.estimate ? 'green' : 'red'}>
              Q{q.quarter} {q.year}: {q.estimate.toFixed(2)} → {q.actual.toFixed(2)}
              {' '}({q.surprise_percent >= 0 ? '+' : ''}{q.surprise_percent.toFixed(1)}%)
            </Text>
          ))}
        </Stack>
      )}
    </Paper>
  )
}

export default function TopVolumePanel() {
  const [topByVolume, setTopByVolume] = useState([])
  const [earningsByTicker, setEarningsByTicker] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const { open, closedRange } = useMarketStatus()

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    apiFetch('/scanner/movers')
      .then(r => r.ok ? r.json() : r.json().then(b => Promise.reject(b.detail || r.statusText)))
      .then(data => {
        const top = [...data]
          .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
          .slice(0, TOP_N)
        setTopByVolume(top)
        setEarningsByTicker({})
        setLoading(false)

        const tickers = top.map(m => m.ticker).join(',')
        if (tickers) {
          apiFetch(`/ai/earnings?tickers=${encodeURIComponent(tickers)}`)
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(({ earnings }) => setEarningsByTicker(earnings || {}))
            .catch(() => {}) // tooltip falls back to "No earnings data" per-ticker
        }
      })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, POLL_INTERVAL)
    return () => clearInterval(id)
  }, [load])

  return (
    <Paper p="md">
      <Group justify="space-between" mb="xs">
        <Text size="xs" fw={600} tt="uppercase" c="dimmed">Top {TOP_N} by Volume</Text>
      </Group>

      {error && <Text c="red" size="sm" py="xs">Error: {error}</Text>}

      {!loading && !error && topByVolume.length === 0 && (
        <Text c="dimmed" size="sm" py="xs">No movers found.</Text>
      )}

      {!loading && !error && topByVolume.length > 0 && !open && (
        <Text size="xs" c="dimmed" mb="xs">
          Last trading day data — market closed{closedRange ? ` (${closedRange})` : ''}.
        </Text>
      )}

      {topByVolume.length > 0 && (
        <BarChart
          h={220}
          data={topByVolume}
          dataKey="ticker"
          series={[{ name: 'volume', color: 'blue.6' }]}
          valueFormatter={formatVolume}
          withBarValueLabel
          tickLine="none"
          tooltipProps={{
            content: ({ active, payload, label }) => (
              <EarningsTooltip
                active={active}
                payload={payload}
                label={label}
                earningsByTicker={earningsByTicker}
              />
            ),
          }}
        />
      )}
    </Paper>
  )
}
