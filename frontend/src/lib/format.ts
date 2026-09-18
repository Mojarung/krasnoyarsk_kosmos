const integer = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const oneDigit = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 })
const compact = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 })
const shortDate = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
const dayMonth = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' })
const dateTime = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })

export const DAY_MS = 86_400_000

export const fmt = {
  int: (value: number) => integer.format(value),
  num: (value: number | null | undefined) => (value == null ? '-' : oneDigit.format(value)),
  ha: (value: number) => (value >= 100 ? integer.format(value) : oneDigit.format(value)),
  pct: (value: number | null | undefined) => (value == null ? '-' : percent.format(value)),
  compact: (value: number) => compact.format(value),
  score: (value: number | null | undefined) => (value == null ? '-' : value.toFixed(3)),
  date: (iso: string) => shortDate.format(new Date(iso)),
  dayMonth: (iso: string | number) => dayMonth.format(new Date(iso)),
  dateTimeUtc: (iso: string) => `${dateTime.format(new Date(iso))} UTC`,
  money: (value: number, currency: string) =>
    new Intl.NumberFormat('ru-RU', { style: 'currency', currency, maximumFractionDigits: 0, notation: value >= 1e7 ? 'compact' : 'standard' }).format(value),
}

export function toIsoDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

export function dayNumber(iso: string): number {
  return Math.floor(Date.parse(iso) / DAY_MS)
}
