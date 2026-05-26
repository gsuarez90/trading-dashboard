import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, Group, Paper, ScrollArea, Table, Text } from '@mantine/core'
import { useMarketStatus } from '../utils/market'
import { apiFetch } from '../utils/api'

const POLL_INTERVAL = 60_000

export default function ScannerPanel() {
  const [movers, setMovers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const { open, closedRange } = useMarketStatus()

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    apiFetch('/scanner/movers')
      .then(r => r.ok ? r.json() : r.json().then(b => Promise.reject(b.detail || r.statusText)))
      .then(data => { setMovers(data); setLoading(false) })
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
        <Text size="xs" fw={600} tt="uppercase" c="dimmed">Scanner — Top Movers</Text>
        <Button variant="subtle" size="xs" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </Button>
      </Group>

      {error && <Text c="red" size="sm" py="xs">Error: {error}</Text>}

      {!loading && !error && movers.length === 0 && (
        <Text c="dimmed" size="sm" py="xs">No movers found.</Text>
      )}

      {!loading && !error && movers.length > 0 && !open && (
        <Text size="xs" c="dimmed" mb="xs">
          Last trading day data — market closed{closedRange ? ` (${closedRange})` : ''}.
        </Text>
      )}

      {movers.length > 0 && (
        <ScrollArea>
          <Table
            highlightOnHover
            style={{ fontSize: 12, fontFamily: 'var(--mono)', whiteSpace: 'nowrap' }}
          >
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Ticker</Table.Th>
                <Table.Th>Price</Table.Th>
                <Table.Th>Change %</Table.Th>
                <Table.Th>Volume</Table.Th>
                <Table.Th>High</Table.Th>
                <Table.Th>Low</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {movers.map(m => (
                <Table.Tr key={m.ticker}>
                  <Table.Td fw={700}>{m.ticker}</Table.Td>
                  <Table.Td>${m.price?.toFixed(2)}</Table.Td>
                  <Table.Td>
                    <Text
                      size="xs"
                      c={m.change_pct >= 0 ? 'green' : 'red'}
                      ff="mono"
                      inherit
                    >
                      {m.change_pct >= 0 ? '+' : ''}{m.change_pct?.toFixed(2)}%
                    </Text>
                  </Table.Td>
                  <Table.Td>{m.volume?.toLocaleString()}</Table.Td>
                  <Table.Td>${m.high?.toFixed(2)}</Table.Td>
                  <Table.Td>${m.low?.toFixed(2)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
    </Paper>
  )
}
