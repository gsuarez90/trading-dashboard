import { useEffect, useState } from 'react'
import { apiFetch } from './api'

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/**
 * Returns current ET market status using a pure weekday calculation.
 * Used as the instant initial value before the backend responds.
 * Holiday awareness comes from the backend via useMarketStatus().
 */
export function getMarketStatus() {
  const now = new Date()
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      weekday: 'long',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).formatToParts(now).map(x => [x.type, x.value])
  )

  const d = DAYS.indexOf(p.weekday)
  const h = parseInt(p.hour) % 24
  const m = parseInt(p.minute)

  const isOpen = d >= 1 && d <= 5 && (h > 9 || (h === 9 && m >= 30)) && h < 16

  if (isOpen) return { open: true, closedRange: null, isTodayTradingDay: false, nextOpenDate: null }

  // Days forward to next weekday open (0 = opens today, pre-market)
  let fwd = (d >= 1 && d <= 5 && (h < 9 || (h === 9 && m < 30))) ? 0 : 1
  while ([0, 6].includes((d + fwd) % 7)) fwd++

  // Days back to last weekday close
  let back = (d >= 1 && d <= 5 && h >= 16) ? 0 : 1
  while ([0, 6].includes((d - back + 7) % 7)) back++

  const fmtDate = offsetDays =>
    new Date(now.getTime() + offsetDays * 86_400_000).toLocaleDateString('en-US', {
      timeZone: 'America/New_York',
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    })

  const isTodayTradingDay = fwd === 0

  return {
    open: false,
    closedRange: `${fmtDate(-back)} → ${fmtDate(fwd)}, 9:30 AM ET`,
    isTodayTradingDay,
    nextOpenDate: fmtDate(fwd),
  }
}

/**
 * React hook — returns market status, starting from the local calculation
 * and updating open/closed from the backend once the fetch resolves.
 * Falls back silently to the local calculation if the backend call fails.
 */
export function useMarketStatus() {
  const [status, setStatus] = useState(() => getMarketStatus())

  useEffect(() => {
    apiFetch('/market/status')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(({ is_open, next_open_date }) => {
        setStatus(prev => {
          const update = { ...prev, open: is_open }
          if (next_open_date) {
            const nextFormatted = new Date(next_open_date + 'T12:00:00')
              .toLocaleDateString('en-US', {
                timeZone: 'America/New_York',
                weekday: 'short', month: 'short', day: 'numeric',
              })
            update.nextOpenDate = nextFormatted
            const backPart = prev.closedRange ? prev.closedRange.split(' → ')[0] : ''
            if (backPart) update.closedRange = `${backPart} → ${nextFormatted}, 9:30 AM ET`
          }
          return update
        })
      })
      .catch(() => {})
  }, [])

  return status
}
