import type { FeatureCollection, MultiPolygon, Polygon } from 'geojson'

export type WorkAction = 'planting' | 'assisted' | 'natural' | 'agro' | 'erosion' | 'none' | 'unknown'
export interface WorkProps {
  id: number; action: WorkAction; label: string; area_ha: number
  severity: number; severity_label: string; landcover: string; landcover_label: string
}
export interface WorkMap {
  id: string; event_id: string; status: 'idle' | 'queued' | 'running' | 'ready' | 'error'; message?: string
  bbox?: [number, number, number, number]; area_ha?: number
  totals?: { action: WorkAction; label: string; area_ha: number }[]
  map?: FeatureCollection<Polygon | MultiPolygon, WorkProps>
}
export const WORK_COLORS: Record<WorkAction, string> = {
  planting: '#cc795d', assisted: '#dfbf79', natural: '#a2b084', agro: '#c4a080',
  erosion: '#bc925b', none: '#aaa69a', unknown: '#888b8a',
}
