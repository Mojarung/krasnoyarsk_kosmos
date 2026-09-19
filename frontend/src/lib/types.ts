import type { Feature, FeatureCollection, MultiPolygon, Point, Polygon } from 'geojson'

export type AreaGeometry = Polygon | MultiPolygon
export type HotspotKind = 'fire' | 'technogenic' | 'glint'

export type FireEventStatus = 'linked' | 'hotspot_only' | 'burn_only' | 'ambiguous'
export interface FireEventSummary {
  id: string
  status: FireEventStatus
  date_from: string
  date_to: string
  first_seen: string | null
  last_seen: string | null
  observed_days: number
  hotspot_count: number
  scene_ids: string[]
  area_ha: number | null
  candidate_ids: string[]
}
export interface FireEventMethod {
  association: string
  observation: string
  af_radius_m: number
  af_gap_hours: number
  burn_radius_m: number
}
export interface FireEventList {
  total: number
  items: FireEventSummary[]
  offset: number
  limit: number
  method: FireEventMethod
}
export interface FireEventDetail extends FireEventSummary {
  burn: { area_ha: number; by_severity: SeverityShare[] } | null
  restoration: (Report['restoration'] & { note: string }) | null
  timeline: { at: string; kind: 'viirs'; hotspot_count: number; satellites: string[]; scene_ids: string[]; confidence_mean: number }[]
  scenes: { id: string; date_pre: string; date_post: string; cloud_frac: number | null; area_ha: number }[]
  evidence: { hotspot_id: number; distance_m: number }[]
  method: FireEventMethod
  bbox: [number, number, number, number] | null
  map: FeatureCollection
  scope_note: string
  generated_at: string
}
export type PassportTarget = { type: 'list' } | { type: 'event'; id: string } | { type: 'hotspot'; id: number } | { type: 'scene'; id: string }

export interface HotspotProps {
  id: number
  kind: HotspotKind
  kind_label: string
  reason: string | null
  acquired_at: string
  ts: number
  satellite: string | null
  scene_id: string
  source: string
  bt_i4: number
  bt_i5: number
  frp_mw: number | null
  frp_saturated: boolean
  confidence: number
  landcover: string
  is_night: boolean
  t2m: number | null
  rh2m: number | null
  wind_speed: number | null
}

export interface BurnAreaProps {
  contour_id: number
  scene_id: string
  fire_event_id: string | null
  date_pre: string
  date_post: string
  area_ha: number
  sev1_ha: number
  sev2_ha: number
  sev3_ha: number
  clipped: boolean
  area_crs: string
}

export type HotspotCollection = FeatureCollection<Point, HotspotProps>
export type BurnCollection = FeatureCollection<MultiPolygon, BurnAreaProps>

export interface SeverityShare {
  severity: 1 | 2 | 3
  label: string
  area_ha: number
  share: number
}

export interface Quality {
  af_scenes: number
  bs_scenes: number
  f1_af: number | null
  precision_af: number | null
  recall_af: number | null
  iou_burn: number | null
  iou_severity: number[] | null
  miou_sev: number | null
  score: number | null
  note: string
}

export interface RestorationItem {
  action: string
  label: string
  area_ha: number
  rate_per_ha: number
  cost: number
  counts_as_damage: boolean
  breakdown: { landcover_label: string; severity_label: string; severity: number; area_ha: number }[]
}

export interface EmissionSpecies {
  key: string
  label: string
  name: string
  about: string
  tonnes: number
}

export interface Emissions {
  disclaimer: string
  method: string
  sources: string
  dry_matter_t: number
  co2e_t: number
  species: EmissionSpecies[]
  by_landcover: {
    landcover: string
    label: string
    area_ha: number
    dry_matter_t: number
    share: number
    load_t_ha: number
  }[]
  by_severity: { severity: number; label: string; dry_matter_t: number; completeness: number }[]
}

export interface ProfileYear {
  year: number
  hotspots: number
  active_days: number
  frp_mw: number | null
  contours: number
  area_ha: number
  area_deviation: number | null
  hotspot_deviation: number | null
  in_query: boolean
}

export interface Profile {
  query: { geometry: AreaGeometry; date_from: string; date_to: string; area_km2: number }
  coverage: { first_day: string | null; last_day: string | null; af_scenes: number; bs_scenes: number; years: number }
  years: ProfileYear[]
  season: { month: number; label: string; hotspots: number; hotspots_per_year: number; area_ha: number; years_seen: number }[]
  peak_month: string | null
  fire_season: { from: string; to: string; months: number; share: number } | null
  worst_year: number | null
  recurrence: {
    cell_area_ha: number
    touched_cells: number
    touched_ha: number
    touched_share: number | null
    repeat_cells: number
    repeat_ha: number
    repeat_share: number | null
    max_years: number
    buckets: { years: number; cells: number; area_ha: number; share: number }[]
  }
  method: string
}

export interface Report {
  generated_at: string
  query: { geometry: AreaGeometry; date_from: string; date_to: string }
  burn: {
    total_ha: number
    scenes: number
    contours: number
    mean_ha: number
    median_ha: number
    max_ha: number
    query_area_km2: number
    burned_share: number | null
    severity_index: number | null
    by_severity: SeverityShare[]
    by_landcover: { landcover: string; label: string; area_ha: number }[]
    by_month: { month: string; area_ha: number; contours: number }[]
    largest: { contour_id: number; scene_id: string; date_post: string; area_ha: number; lon: number; lat: number }[]
  }
  hotspots: {
    raw_total: number
    fire: number
    technogenic: number
    glint: number
    fire_clusters: number
    false_dispatches_prevented: number
    filtered_share: number
    by_satellite: Record<string, number>
    by_day: { day: string; fire: number; technogenic: number; glint: number }[]
    bt_i4_mean_k: number | null
    bt_i4_max_k: number | null
    power: {
      total_mw: number | null
      max_mw: number | null
      mean_mw: number | null
      saturated: number
      saturated_share: number | null
      top: {
        day: string
        hotspots: number
        frp_mw: number | null
        frp_max_mw: number | null
        landcover: string
        label: string
        lon: number
        lat: number
      }[]
    }
    delta_mean_k: number | null
    confidence_mean: number | null
    night_share: number | null
    active_days: number
    passes_with_fire: number
    weather: { t2m_mean_c: number | null; rh2m_mean: number | null; wind_mean_ms: number | null; wind_max_ms: number | null }
    by_landcover: { landcover: string; label: string; n: number; share: number }[]
    by_month: { month: string; n: number }[]
    peak_month: string | null
  }
  quality: Quality | null
  emissions: Emissions
  restoration: {
    currency: string
    disclaimer: string
    total_cost: number
    damage_area_ha: number
    natural_area_ha: number
    items: RestorationItem[]
  }
  method: Record<string, string>
}

export interface QueryResult {
  hotspots: HotspotCollection
  burn_areas?: BurnCollection
  report: Report
}

export interface RegionProps {
  id: string
  name: string
  aliases: string[]
}

export interface Meta {
  aoi: Feature<Polygon, { name: string; area_km2: number }>
  regions: FeatureCollection<AreaGeometry, RegionProps>
  data: {
    af_scenes: number
    bs_scenes: number
    pending_scenes: number
    hotspots: number
    persistent_sources: number
    burn_ha: number
    date_min: string | null
    date_max: string | null
    models: string[]
  }
  severity: { severity: number; label: string; color: string }[]
  pipeline: { stage: string; label: string }[]
  agent: { llm: boolean; model: string | null }
  integrations: { firms: boolean }
  tiles_version: number
}

export interface TimelineDay {
  day: string
  fire: number
  filtered: number
  burn_ha: number
}

export interface SceneSummary {
  id: string
  kind: 'af' | 'bs'
  status: string
  acquired_at: string | null
  satellite: string | null
  date_pre: string | null
  date_post: string | null
  cloud_frac: number | null
  model_name: string | null
  stats: Record<string, unknown>
  corners: [number, number][] | null
  quicklooks: string[]
}

export interface JobEvent {
  id: string
  scene_id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  stage: string
  progress: number
  message: string
}

export interface AlertItem {
  id: number
  zone_id: number
  zone_name: string
  scene_id: string
  n_hotspots: number
  acquired_at: string
  lon: number
  lat: number
  is_read?: boolean
}

export interface Zone {
  id: number
  name: string
  geometry: AreaGeometry
  webhook_url: string | null
}

export interface PipelineMetrics {
  scenes_last_minute: number
  by_kind: Record<string, { scenes: number; mean_ms: number; p95_ms: number }>
}

export type ResponseLevel = 'critical' | 'high' | 'medium' | 'low'

export interface ResponseThreat {
  name: string
  kind: string
  lon: number
  lat: number
  distance_km: number
  horizon_h: number | null
}

export interface ResponseCard {
  id: string
  day: string
  last_seen: string
  lon: number
  lat: number
  hotspots: number
  prev_hotspots: number
  growth: 'new' | 'doubling' | 'steady' | 'fading'
  frp_mw: number | null
  frp_max_mw: number | null
  landcover: string
  landcover_label: string
  is_night: boolean
  weather: { wind_ms: number | null; wind_dir_deg: number | null; rh2m: number | null; t2m_c: number | null }
  priority: { score: number; level: ResponseLevel; label: string; parts: Record<string, number> }
  spread: {
    rate_kmh: number | null
    heading_deg: number | null
    ellipses: { hours: number; head_km: number; geometry: Polygon }[]
  }
  /** null - OpenStreetMap не ответил или очаг вне верхушки списка. */
  threats: ResponseThreat[] | null
  arrival: { station: string; lon: number; lat: number; distance_km: number; eta_min: number } | null
  road_km: number | null
  method: { key: string; label: string; resources: string[] }
  steps: string[]
}

export interface ResponsePlan {
  generated_at: string
  window: { from: string | null; to: string | null; days: number }
  fires_total: number
  by_level: Record<ResponseLevel, number>
  /** osm: pending - OpenStreetMap ещё отвечает в фоне, план стоит переспросить. */
  external: { wind: boolean; osm: 'ready' | 'pending' | 'failed' | 'off' }
  cards: ResponseCard[]
  disclaimer: string
  sources: string
}

export interface AreaSuggestion {
  mode: 'random' | 'fire'
  geometry: Polygon
  date_pre: string
  date_post: string
  label: string
}

export interface AreaAcquisitionResult {
  jobs: { job_id: string; scene_id: string }[]
  hotspots: {
    status: 'ready' | 'unavailable'
    imported: number
    existing: number
    products?: string[]
    message?: string
  }
  burns: {
    status: 'queued' | 'skipped'
    jobs: number
    message?: string
  }
}
