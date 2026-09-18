import type { Feature, FeatureCollection, MultiPolygon, Point, Polygon } from 'geojson'

export type AreaGeometry = Polygon | MultiPolygon
export type HotspotKind = 'fire' | 'technogenic' | 'glint'

export interface HotspotProps {
  id: number
  kind: HotspotKind
  kind_label: string
  reason: string | null
  acquired_at: string
  ts: number
  satellite: string | null
  scene_id: string
  bt_i4: number
  bt_i5: number
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
