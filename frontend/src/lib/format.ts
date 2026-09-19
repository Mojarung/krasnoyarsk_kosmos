const integer = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const oneDigit = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 })
const compact = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 })
// Метрики печатались через toFixed и давали точку рядом с остальными числами,
// набранными по-русски через запятую: 0.586 и 0,960 на одном экране.
const threeDigits = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const twoDigits = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const shortDate = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
const dayMonth = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' })
const dateTime = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })
const monthLong = new Intl.DateTimeFormat('ru-RU', { month: 'long', timeZone: 'UTC' })
const monthShort = new Intl.DateTimeFormat('ru-RU', { month: 'short', timeZone: 'UTC' })

export const DAY_MS = 86_400_000

export const fmt = {
  int: (value: number) => integer.format(value),
  num: (value: number | null | undefined) => (value == null ? '-' : oneDigit.format(value)),
  ha: (value: number) => (value >= 100 ? integer.format(value) : oneDigit.format(value)),
  pct: (value: number | null | undefined) => (value == null ? '-' : percent.format(value)),
  compact: (value: number) => compact.format(value),
  score: (value: number | null | undefined) => (value == null ? '—' : threeDigits.format(value)),
  ratio: (value: number | null | undefined) => (value == null ? '—' : twoDigits.format(value)),
  date: (iso: string) => shortDate.format(new Date(iso)),
  month: (key: string) => `${monthLong.format(monthStart(key))} ${key.slice(0, 4)}`,
  monthShort: (key: string) => monthShort.format(monthStart(key)).replace('.', ''),
  dayMonth: (iso: string | number) => dayMonth.format(new Date(iso)),
  dateTimeUtc: (iso: string) => `${dateTime.format(new Date(iso))} UTC`,
  money: (value: number, currency: string) =>
    new Intl.NumberFormat('ru-RU', { style: 'currency', currency, maximumFractionDigits: 0, notation: value >= 1e7 ? 'compact' : 'standard' }).format(value),
}

/** Начало месяца `YYYY-MM` в UTC. */
export function monthStart(key: string): number {
  return Date.parse(`${key.slice(0, 7)}-01T00:00:00Z`)
}

/** Непрерывный ряд ключей `YYYY-MM` от месяца `from` до месяца `to` включительно. */
export function monthRange(from: string, to: string): string[] {
  const cursor = new Date(monthStart(from))
  const last = monthStart(to)
  const keys: string[] = []
  while (cursor.getTime() <= last && keys.length < 600) {
    keys.push(toIsoDate(cursor.getTime()).slice(0, 7))
    cursor.setUTCMonth(cursor.getUTCMonth() + 1)
  }
  return keys
}

/** Помесячный ряд без пропусков: месяцы без данных получают ноль. */
export function denseMonths<T>(range: string[], rows: T[], key: (row: T) => string, value: (row: T) => number) {
  const index = new Map(rows.map((row) => [key(row).slice(0, 7), value(row)]))
  return range.map((month) => ({ month, value: index.get(month) ?? 0 }))
}

export function toIsoDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

export function dayNumber(iso: string): number {
  return Math.floor(Date.parse(iso) / DAY_MS)
}

export function plural(n: number, forms: [one: string, few: string, many: string]): string {
  const value = Math.abs(Math.round(n))
  const form = value % 10 === 1 && value % 100 !== 11 ? forms[0] : value % 10 >= 2 && value % 10 <= 4 && !(value % 100 >= 12 && value % 100 <= 14) ? forms[1] : forms[2]
  return `${fmt.int(value)} ${form}`
}
