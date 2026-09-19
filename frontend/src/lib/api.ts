import type { FeatureCollection, Point } from 'geojson'
import type { Inspection, InspectionInput } from './inspections'
import type { VegetationReport } from './vegetation'
import type {
  AlertItem,
  FireEventDetail,
  FireEventList,
  FireEventStatus,
  AreaGeometry,
  AreaSuggestion,
  Meta,
  PipelineMetrics,
  Profile,
  Quality,
  QueryResult,
  ResponsePlan,
  SceneSummary,
  TimelineDay,
  Zone,
} from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : `Ошибка ${response.status}`
    throw new ApiError(response.status, detail)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}

export interface QueryParams {
  geometry: AreaGeometry
  date_from: string
  date_to: string
}

export const api = {
  startVegetation: (eventId: string, retry = false, signal?: AbortSignal) => post<VegetationReport>(`${BASE}/events/${encodeURIComponent(eventId)}/vegetation?retry=${retry}`, {}, signal),
  vegetation: (jobId: string, signal?: AbortSignal) => request<VegetationReport>(`${BASE}/vegetation/${jobId}`, { signal }),
  createInspection: (body: InspectionInput) => post<Inspection>(`${BASE}/inspections`, body),
  inspections: (eventId: string, signal?: AbortSignal) => request<{ items: Inspection[] }>(`${BASE}/inspections?${new URLSearchParams({ event_id: eventId })}`, { signal }),
  sharedInspection: (token: string) => request<Inspection>(`${BASE}/inspections/shared/${encodeURIComponent(token)}`),
  events: (params: QueryParams, status: FireEventStatus | 'all', offset = 0, signal?: AbortSignal) =>
    post<FireEventList>(`${BASE}/events?${new URLSearchParams({ status, offset: String(offset) })}`, params, signal),
  event: (id: string, signal?: AbortSignal) => request<FireEventDetail>(`${BASE}/events/${encodeURIComponent(id)}`, { signal }),
  resolveEvent: (target: { type: 'hotspot' | 'scene'; id: string | number }, signal?: AbortSignal) =>
    request<{ id: string }>(`${BASE}/events/resolve?${new URLSearchParams({ [target.type === 'hotspot' ? 'hotspot_id' : 'scene_id']: String(target.id) })}`, { signal }),
  meta: () => request<Meta>(`${BASE}/meta`),
  timeline: () => request<TimelineDay[]>(`${BASE}/timeline`),
  query: (params: QueryParams, signal?: AbortSignal) => post<QueryResult>(`${BASE}/query?contours=false`, params, signal),
  sources: () => request<FeatureCollection<Point>>(`${BASE}/technogenic/sources`),
  scene: (id: string) => request<SceneSummary>(`${BASE}/scenes/${id}`),
  scenes: (params: Record<string, string>) =>
    request<{ total: number; items: SceneSummary[] }>(`${BASE}/scenes?${new URLSearchParams(params)}`),
  reprocess: (id: string) => post<{ job_id: string; scene_id: string }>(`${BASE}/scenes/${id}/reprocess`, {}),
  uploadScene: (form: FormData) => request<{ job_id: string; scene_id: string }>(`${BASE}/scenes`, { method: 'POST', body: form }),
  jobs: () => request<{ counts: Record<string, number>; items: import('./types').JobEvent[] }>(`${BASE}/jobs?limit=12`),
  pipelineMetrics: () => request<PipelineMetrics>(`${BASE}/metrics/pipeline`),
  quality: () => request<Quality | null>(`${BASE}/metrics/quality`),
  profile: (params: QueryParams, signal?: AbortSignal) => post<Profile>(`${BASE}/profile`, params, signal),
  responsePlan: (params: QueryParams, signal?: AbortSignal) => post<ResponsePlan>(`${BASE}/response-plan`, params, signal),
  suggestArea: (mode: 'random' | 'fire') => request<AreaSuggestion>(`${BASE}/acquisitions/suggest?mode=${mode}`),
  acquire: (geometry: AreaGeometry, date_pre: string, date_post: string) =>
    post<{ jobs: { job_id: string; scene_id: string }[] }>(`${BASE}/acquisitions`, { geometry, date_pre, date_post }),
  zones: () => request<Zone[]>(`${BASE}/zones`),
  createZone: (name: string, geometry: AreaGeometry, webhook_url: string | null) =>
    post<Zone>(`${BASE}/zones`, { name, geometry, webhook_url }),
  deleteZone: (id: number) => request<void>(`${BASE}/zones/${id}`, { method: 'DELETE' }),
  alerts: () => request<{ unread: number; items: AlertItem[] }>(`${BASE}/alerts`),
  markAlertsRead: () => request<void>(`${BASE}/alerts/read`, { method: 'POST' }),
  quicklookUrl: (sceneId: string, name: string) => `${BASE}/scenes/${sceneId}/quicklooks/${name}.webp`,
}

export async function download(path: string, params: QueryParams, filename: string): Promise<void> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, body?.detail ?? `Ошибка ${response.status}`)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? filename
  const url = URL.createObjectURL(await response.blob())
  const link = Object.assign(document.createElement('a'), { href: url, download: name })
  link.click()
  URL.revokeObjectURL(url)
}

export function curlFor(path: string, params: QueryParams): string {
  const origin = window.location.origin
  return `curl -X POST '${origin}${path}' -H 'Content-Type: application/json' -d '${JSON.stringify(params)}'`
}

export interface AgentCardData {
  title: string
  date_from: string
  date_to: string
  notes: string[]
  empty: boolean
  kpis: { label: string; value: number; unit: string; sub: string }[]
  severity: import('./types').SeverityShare[]
  largest: { contour_id: number; scene_id: string; date_post: string; area_ha: number; lon: number; lat: number } | null
}

export type AgentAction =
  | { type: 'set_query'; region_id: string; geometry: AreaGeometry; date_from: string; date_to: string }
  | { type: 'focus'; lon: number; lat: number; zoom: number; scene_id: string }
  | { type: 'open_tab'; tab: 'report' | 'metrics' | 'restoration' | 'technogenic' | 'response' }

export type AgentEvent =
  | { event: 'token'; data: { text: string } }
  | { event: 'done'; data: { mode: string; model?: string } }
  | { event: 'card'; data: AgentCardData }
  | { event: 'refusal'; data: { examples: string[] } }
  | { event: 'action'; data: AgentAction }

export async function* streamSse(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) throw new ApiError(response.status, `Ошибка ${response.status}`)
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value.replaceAll('\r\n', '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      let event = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trim())
      }
      if (data.length) yield { event, data: JSON.parse(data.join('\n')) } as AgentEvent
      boundary = buffer.indexOf('\n\n')
    }
  }
}
