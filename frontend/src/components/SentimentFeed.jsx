import { useEffect, useState } from 'react'
import { Badge, Paper, ScrollArea, Table, Text } from '@mantine/core'
import { apiFetch } from '../utils/api'

function sentimentColor(label) {
  if (label === 'bullish') return 'green'
  if (label === 'bearish') return 'red'
  return 'gray'
}

export default function SentimentFeed() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    apiFetch('/ai/sentiment')
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(data => { setRows(data.sentiment || []); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  return (
    <Paper p="md">
      <Text size="xs" fw={600} tt="uppercase" c="dimmed" mb="xs">
        Sentiment — 3-Day News
      </Text>

      {loading && <Text c="dimmed" size="sm" py="xs">Loading…</Text>}
      {error && <Text c="red" size="sm" py="xs">Error: {error}</Text>}

      {!loading && !error && rows.length === 0 && (
        <Text c="dimmed" size="sm" py="xs">No sentiment data.</Text>
      )}

      {rows.length > 0 && (
        <ScrollArea>
          <Table
            highlightOnHover
            style={{ fontSize: 12, fontFamily: 'var(--mono)', whiteSpace: 'nowrap' }}
          >
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Ticker</Table.Th>
                <Table.Th>Score</Table.Th>
                <Table.Th>Label</Table.Th>
                <Table.Th>Articles</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map(r => (
                <Table.Tr key={r.ticker}>
                  <Table.Td fw={700}>{r.ticker}</Table.Td>
                  <Table.Td>
                    <Text
                      size="xs"
                      c={sentimentColor(r.label)}
                      ff="mono"
                      inherit
                    >
                      {r.score?.toFixed(4)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      color={sentimentColor(r.label)}
                      size="xs"
                      radius="xl"
                      variant="light"
                    >
                      {r.label}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{r.article_count}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
    </Paper>
  )
}
