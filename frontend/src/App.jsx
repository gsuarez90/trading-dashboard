import { Container, Group, SimpleGrid, Stack, Text } from '@mantine/core'
import DailySummaryPanel from './components/DailySummaryPanel'
import ChatPanel from './components/ChatPanel'
import ScannerPanel from './components/ScannerPanel'
import SentimentFeed from './components/SentimentFeed'
import TopVolumePanel from './components/TopVolumePanel'
import PortfolioView from './components/PortfolioView'
import PaperTradingPanel from './components/PaperTradingPanel'
import LiveTrackingPanel from './components/LiveTrackingPanel'
import GuardrailsPanel from './components/GuardrailsPanel'

// Private panels are hidden in the synthetic (public demo) build.
const isPrivate = import.meta.env.VITE_PORTFOLIO_MODE !== 'synthetic'

export default function App() {
  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <Group>
          <Text fw={700} size="sm" style={{ letterSpacing: '0.04em' }}>
            AI Trading Dashboard
          </Text>
        </Group>

        <DailySummaryPanel />
        <ChatPanel />

        {/* Two-column on md+, single-column on mobile */}
        <SimpleGrid cols={{ base: 1, md: 2 }}>
          <ScannerPanel />
          <SentimentFeed />
        </SimpleGrid>

        <TopVolumePanel />

        {isPrivate && (
          <>
            <PaperTradingPanel />
            <LiveTrackingPanel />
            <GuardrailsPanel />
          </>
        )}

        <PortfolioView />
      </Stack>
    </Container>
  )
}
