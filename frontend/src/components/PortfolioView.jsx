import { useCallback, useEffect, useState } from 'react'
import { Button, Group, Paper, ScrollArea, Table, Text } from '@mantine/core'
import { apiFetch } from '../utils/api'

const MODE = import.meta.env.VITE_PORTFOLIO_MODE || 'synthetic'
const POLL_INTERVAL = 90_000

export default function PortfolioView() {
  const [portfolio, setPortfolio] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    apiFetch(`/portfolio/?mode=${MODE}`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : r.json().then(b => Promise.reject(b.detail || r.statusText)))
      .then(data => { setPortfolio(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, POLL_INTERVAL)
    return () => clearInterval(id)
  }, [load])

  const positions = portfolio?.positions || []

  return (
    <Paper p="md">
      <Group justify="space-between" mb="xs">
        <Text size="xs" fw={600} tt="uppercase" c="dimmed">Portfolio</Text>
        <Button variant="subtle" size="xs" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </Button>
      </Group>

      {error && <Text c="red" size="sm" py="xs">Error: {error}</Text>}

      {portfolio && (
        <>
          <Text size="sm" ff="mono" mb="xs">
            Cash:{' '}
            <Text span fw={700} ff="mono">
              ${portfolio.cash?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </Text>
          </Text>

          {positions.length === 0 ? (
            <Text c="dimmed" size="sm" py="xs">No open positions.</Text>
          ) : (
            <ScrollArea>
              <Table
                highlightOnHover
                style={{ fontSize: 12, fontFamily: 'var(--mono)', whiteSpace: 'nowrap' }}
              >
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Ticker</Table.Th>
                    <Table.Th>Shares</Table.Th>
                    <Table.Th>Avg Cost</Table.Th>
                    <Table.Th>Price</Table.Th>
                    <Table.Th>Unreal. P&L</Table.Th>
                    <Table.Th>%</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {positions.map(p => (
                    <Table.Tr key={p.ticker}>
                      <Table.Td fw={700}>{p.ticker}</Table.Td>
                      <Table.Td>{p.shares}</Table.Td>
                      <Table.Td>${p.avg_cost?.toFixed(2)}</Table.Td>
                      <Table.Td>${p.current_price?.toFixed(2) ?? '—'}</Table.Td>
                      <Table.Td>
                        <Text size="xs" c={p.unrealized_pnl >= 0 ? 'green' : 'red'} ff="mono" inherit>
                          {p.unrealized_pnl != null
                            ? `${p.unrealized_pnl >= 0 ? '+' : ''}$${p.unrealized_pnl.toFixed(2)}`
                            : '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c={p.unrealized_pnl_pct >= 0 ? 'green' : 'red'} ff="mono" inherit>
                          {p.unrealized_pnl_pct != null
                            ? `${p.unrealized_pnl_pct >= 0 ? '+' : ''}${p.unrealized_pnl_pct.toFixed(2)}%`
                            : '—'}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          )}
        </>
      )}
    </Paper>
  )
}
