import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider, createTheme } from '@mantine/core'
import '@mantine/core/styles.css'
import './index.css'
import App from './App.jsx'

// Map the existing GitHub-dark color palette onto Mantine's dark shade system.
// dark[6] → --surface (#161b22), dark[7] → --bg (#0d0f14), dark[4] → --border (#30363d)
const theme = createTheme({
  colors: {
    dark: [
      '#e6edf3', // [0] --text
      '#c9d1d9', // [1]
      '#8b949e', // [2] --text-muted
      '#6e7681', // [3]
      '#30363d', // [4] --border  ← Mantine uses this for withBorder
      '#21262d', // [5]
      '#161b22', // [6] --surface ← Paper background
      '#0d0f14', // [7] --bg      ← body background
      '#090c10', // [8]
      '#040507', // [9]
    ],
  },
  primaryColor: 'blue',
  defaultRadius: 'sm',
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  fontFamilyMonospace: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
  components: {
    Paper: {
      defaultProps: { withBorder: true },
    },
  },
})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <App />
    </MantineProvider>
  </StrictMode>,
)
