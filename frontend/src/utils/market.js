const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/**
 * Returns current ET market status without a backend call.
 * { open: true } during regular hours (Mon–Fri 9:30–4:00 PM ET)
 * { open: false, closedRange: "Fri May 23 → Mon May 26, 9:30 AM ET" } otherwise
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

  if (isOpen) return { open: true, closedRange: null }

  // Days forward to the next weekday open (0 = opens today, e.g. pre-market weekday)
  let fwd = (d >= 1 && d <= 5 && (h < 9 || (h === 9 && m < 30))) ? 0 : 1
  while ([0, 6].includes((d + fwd) % 7)) fwd++

  // Days back to the last weekday close (0 = closed today, e.g. after 4pm on a weekday)
  let back = (d >= 1 && d <= 5 && h >= 16) ? 0 : 1
  while ([0, 6].includes((d - back + 7) % 7)) back++

  const fmtDate = offsetDays =>
    new Date(now.getTime() + offsetDays * 86_400_000).toLocaleDateString('en-US', {
      timeZone: 'America/New_York',
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    })

  // fwd === 0 means next open is today (pre-market weekday) — briefing generates at 9:35 AM ET
  const isTodayTradingDay = fwd === 0

  return {
    open: false,
    closedRange: `${fmtDate(-back)} → ${fmtDate(fwd)}, 9:30 AM ET`,
    isTodayTradingDay,
    nextOpenDate: fmtDate(fwd),
  }
}
