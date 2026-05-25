const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

// NYSE market holidays — update annually (YYYY-MM-DD in ET)
const MARKET_HOLIDAYS = new Set([
  // 2026
  '2026-01-01', // New Year's Day
  '2026-01-19', // MLK Day
  '2026-02-16', // Presidents' Day
  '2026-04-03', // Good Friday
  '2026-05-25', // Memorial Day
  '2026-07-03', // Independence Day (observed)
  '2026-09-07', // Labor Day
  '2026-11-26', // Thanksgiving
  '2026-12-25', // Christmas
  // 2027
  '2027-01-01', // New Year's Day
  '2027-01-18', // MLK Day
  '2027-02-15', // Presidents' Day
  '2027-03-26', // Good Friday
  '2027-05-31', // Memorial Day
  '2027-07-05', // Independence Day (observed)
  '2027-09-06', // Labor Day
  '2027-11-25', // Thanksgiving
  '2027-12-24', // Christmas (observed)
])

/**
 * Returns current ET market status without a backend call.
 * Accounts for weekends and NYSE market holidays.
 * { open: true } during regular hours (Mon–Fri 9:30–4:00 PM ET, non-holiday)
 * { open: false, closedRange: "Fri May 22 → Tue May 26, 9:30 AM ET" } otherwise
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

  // ISO date string (YYYY-MM-DD) in ET for a given day offset
  const isoDate = offsetDays =>
    new Date(now.getTime() + offsetDays * 86_400_000)
      .toLocaleDateString('en-CA', { timeZone: 'America/New_York' })

  // True if the day at offsetDays from today is a non-trading day
  const isClosedDay = offsetDays => {
    const dow = (d + offsetDays + 700) % 7
    return [0, 6].includes(dow) || MARKET_HOLIDAYS.has(isoDate(offsetDays))
  }

  const todayIsHoliday = MARKET_HOLIDAYS.has(isoDate(0))
  const isOpen = d >= 1 && d <= 5 && !todayIsHoliday &&
    (h > 9 || (h === 9 && m >= 30)) && h < 16

  if (isOpen) return { open: true, closedRange: null, isTodayTradingDay: false, nextOpenDate: null }

  // Days forward to next trading day open (0 = opens today, pre-market on a trading weekday)
  let fwd = (d >= 1 && d <= 5 && !todayIsHoliday && (h < 9 || (h === 9 && m < 30))) ? 0 : 1
  while (isClosedDay(fwd)) fwd++

  // Days back to last trading day close
  let back = (d >= 1 && d <= 5 && !todayIsHoliday && h >= 16) ? 0 : 1
  while (isClosedDay(-back)) back++

  const fmtDate = offsetDays =>
    new Date(now.getTime() + offsetDays * 86_400_000).toLocaleDateString('en-US', {
      timeZone: 'America/New_York',
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    })

  // fwd === 0 means next open is today (pre-market trading day) — briefing generates at 9:35 AM ET
  const isTodayTradingDay = fwd === 0

  return {
    open: false,
    closedRange: `${fmtDate(-back)} → ${fmtDate(fwd)}, 9:30 AM ET`,
    isTodayTradingDay,
    nextOpenDate: fmtDate(fwd),
  }
}
