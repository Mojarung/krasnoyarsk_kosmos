import type { FireEventDetail } from './types'
import { yandexMapsUrl } from './yandex-maps'

export type Coordinates = [longitude: number, latitude: number]
export const PURPOSES = { damage: 'Проверить повреждение', recovery: 'Оценить восстановление', boundary: 'Уточнить границы гари' } as const
export type Purpose = keyof typeof PURPOSES
export interface InspectionInput {
  id: string
  event_id: string
  purpose: Purpose
  note: string
  site: Coordinates
  access: Coordinates | null
}
export interface Inspection extends InspectionInput {
  share_token: string
  created_at: string
  snapshot: Pick<FireEventDetail, 'date_from' | 'date_to' | 'burn' | 'bbox'>
}
export function inspectionId(): string {
  // getRandomValues also works over HTTP on a LAN; randomUUID requires a secure context.
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
export function coordinateLabel(point: Coordinates): string {
  return `${point[1].toFixed(5)}, ${point[0].toFixed(5)}`
}
export function routeUrl(point: Coordinates): string {
  const url = new URL('https://yandex.ru/maps/')
  // rtext uses latitude,longitude, unlike the map's ll parameter.
  url.searchParams.set('rtext', `~${point[1]},${point[0]}`)
  url.searchParams.set('rtt', 'auto')
  return url.toString()
}
export function inspectionMapUrl(task: Pick<Inspection, 'site' | 'access'>): string {
  return task.access ? routeUrl(task.access) : yandexMapsUrl([...task.site, ...task.site])!
}
export function inspectionCardUrl(token: string): string {
  const url = new URL('/', window.location.href)
  url.hash = `inspection=${encodeURIComponent(token)}`
  return url.toString()
}
export function inspectionText(task: Inspection): string {
  return [`Осмотр · ${task.event_id}`, PURPOSES[task.purpose],
    `Место осмотра (широта, долгота): ${coordinateLabel(task.site)}`,
    task.access ? `Место остановки: ${coordinateLabel(task.access)}` : 'Место остановки не выбрано.',
    `Снимки: ${task.snapshot.date_from} — ${task.snapshot.date_to}`,
    task.note, task.access ? 'Проходимость и безопасность не проверены.' : '', inspectionMapUrl(task)].filter(Boolean).join('\n')
}
