export interface VegetationFrame {
  year: number
  status: 'ready' | 'cloudy' | 'missing' | 'error'
  message?: string
  date?: string
  date_to?: string
  role?: 'before' | 'during' | 'after'
  valid_share?: number
  item_id?: string
  provider?: 'earth' | 'planetary'
  rgb_url?: string
  change_url?: string
  comparison?: {
    common_share: number
    compared_ha: number
    delta_ndvi: number | null
    baseline_ndvi: number | null
    current_ndvi: number | null
    baseline_date: string
    season_gap_days?: number
  }
}

export interface VegetationReport {
  georef?: { corners: [[number, number], [number, number], [number, number], [number, number]]; width: number; height: number; bbox: [number, number, number, number] }
  id: string
  event_id: string
  status: 'queued' | 'running' | 'ready' | 'partial' | 'error'
  message?: string | null
  active_year: number | null
  years: number[]
  baseline_year: number
  season: string
  resolution_m: number
  analyzed_ha: number
  frames: VegetationFrame[]
  stage?: 'comparison' | 'history'
  post_fire?: VegetationFrame
  recent?: VegetationFrame
}
