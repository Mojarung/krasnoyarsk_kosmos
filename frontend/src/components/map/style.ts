import type { AddLayerObject, ExpressionSpecification, LayerSpecification, StyleSpecification } from 'maplibre-gl'

/** Множитель размера термоточки по её мощности излучения: 0 МВт - вдвое мельче, 9 МВт - в полтора раза крупнее. */
const POWER_SCALE: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['sqrt', ['max', ['coalesce', ['get', 'frp_mw'], 0], 0]],
  0,
  0.55,
  1,
  0.9,
  3,
  1.5,
]

export const SRC = {
  basemapSat: 'basemap-sat',
  aoi: 'aoi',
  regions: 'regions',
  focus: 'focus',
  query: 'query-geometry',
  burns: 'burns',
  hotspots: 'hotspots',
  sources: 'persistent-sources',
  zones: 'zones',
  scene: 'scene-overlay',
  event: 'event-overlay',
} as const

export const LAYER = {
  burnCenters: 'burn-centers',
  burnFill: 'burn-fill',
  burnLine: 'burn-line',
  severity: 'severity-fill',
  fireGlow: 'fire-glow',
  fireCore: 'fire-core',
  firePulse: 'fire-pulse',
  filtered: 'filtered',
  sources: 'persistent-sources',
  scene: 'scene-overlay',
} as const

export const SEVERITY_ZOOM = 10
/**
 * Внешний контур затемнения — весь мир, а не рамка вокруг зоны. Прежний
 * прямоугольник 15-80° в.д., 30-68° с.ш. на рабочем зуме не было видно, но
 * стоило отдалить до глобуса, и он читался серым клином с прямыми краями.
 *
 * Рёбра разбиты на шаги: на глобусе отрезок между далёкими точками идёт по
 * дуге большого круга, поэтому одна линия от полюса до полюса выгнулась бы
 * внутрь. Полюса подрезаны до ±89,9°, чтобы не ловить вырождение проекции.
 */
const FOCUS_BOUNDS = ((step = 10) => {
  const ring: number[][] = []
  for (let lon = -180; lon <= 180; lon += step) ring.push([lon, -89.9])
  for (let lat = -89.9; lat <= 89.9; lat += step) ring.push([180, lat])
  for (let lon = 180; lon >= -180; lon -= step) ring.push([lon, 89.9])
  for (let lat = 89.9; lat >= -89.9; lat -= step) ring.push([-180, lat])
  ring.push([-180, -89.9])
  return ring
})()

function signedArea(ring: number[][]): number {
  let sum = 0
  for (let i = 0; i < ring.length - 1; i++) sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
  return sum
}

export function focusMask(rings: number[][][]): GeoJSON.Feature<GeoJSON.Polygon> {
  const holes = rings.map((ring) => (signedArea(ring) > 0 ? [...ring].reverse() : ring))
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [FOCUS_BOUNDS, ...holes] } }
}

export type MapTheme = 'dark' | 'light'

const STYLE_URLS: Record<MapTheme, string> = {
  dark: 'https://tiles.openfreemap.org/styles/dark',
  light: 'https://tiles.openfreemap.org/styles/positron',
}
const STYLE_TIMEOUT_MS = 5000
const LOCAL_NAME: ExpressionSpecification = ['coalesce', ['get', 'name:ru'], ['get', 'name'], ['get', 'name_en']]
const SKY: Record<MapTheme, StyleSpecification['sky']> = {
  dark: { 'sky-color': '#0b0a12', 'horizon-color': '#2a1a12', 'fog-color': '#120f0d', 'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.8, 'fog-ground-blend': 0.9, 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 0.6, 7, 0] },
  light: { 'sky-color': '#cfe3f5', 'horizon-color': '#fff1e8', 'fog-color': '#fff8f5', 'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.8, 'fog-ground-blend': 0.9, 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 0.6, 7, 0] },
}
const SATELLITE_LAYER: LayerSpecification = {
  id: SRC.basemapSat,
  type: 'raster',
  source: SRC.basemapSat,
  layout: { visibility: 'none' },
  paint: { 'raster-saturation': -0.2, 'raster-brightness-max': 0.85, 'raster-fade-duration': 250 },
}
const SATELLITE_SOURCE = {
  type: 'raster' as const,
  tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
  tileSize: 256,
  maxzoom: 18,
  attribution: 'Esri, Maxar, Earthstar Geographics',
}

function fallbackStyle(background: string): StyleSpecification {
  return { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': background } }] }
}

/** Подложка OpenFreeMap без ключа. Нет сети - остаётся фон, наши слои работают как обычно. */
export async function loadBaseStyle(theme: MapTheme, background: string): Promise<StyleSpecification> {
  let style: StyleSpecification
  try {
    const response = await fetch(STYLE_URLS[theme], { signal: AbortSignal.timeout(STYLE_TIMEOUT_MS) })
    if (!response.ok) throw new Error(String(response.status))
    style = await response.json()
  } catch {
    style = fallbackStyle(background)
  }
  const layers = style.layers.map((layer) =>
    layer.type === 'symbol' && layer.layout?.['text-field'] ? { ...layer, layout: { ...layer.layout, 'text-field': LOCAL_NAME } } : layer,
  )
  const firstSymbol = layers.findIndex((layer) => layer.type === 'symbol')
  layers.splice(firstSymbol === -1 ? layers.length : firstSymbol, 0, SATELLITE_LAYER)
  return { ...style, projection: { type: 'globe' }, sky: SKY[theme], sources: { ...style.sources, [SRC.basemapSat]: SATELLITE_SOURCE }, layers }
}

export const OVERLAY_SOURCES = new Set<string>(Object.values(SRC).filter((id) => id !== SRC.basemapSat))

const severityColor: ExpressionSpecification = ['match', ['get', 'severity'], 1, '#f2cf72', 2, '#ee8a35', 3, '#d2382f', '#ee8a35']

export function overlayLayers(): AddLayerObject[] {
  return [
    { id: 'focus-mask', type: 'fill', source: SRC.focus, paint: { 'fill-color': '#0a0807', 'fill-opacity': 0.58, 'fill-opacity-transition': { duration: 600 } } },
    { id: 'regions-line', type: 'line', source: SRC.regions, paint: { 'line-color': '#ebe3dd', 'line-opacity': 0.16, 'line-width': 1 } },
    { id: 'aoi-line', type: 'line', source: SRC.aoi, paint: { 'line-color': '#e3b9a4', 'line-opacity': 0.5, 'line-width': 1.4, 'line-dasharray': [3, 2] } },
    { id: 'focus-glow', type: 'fill', source: SRC.query, paint: { 'fill-color': '#e3b9a4', 'fill-opacity': 0.05 } },
    { id: 'focus-halo', type: 'line', source: SRC.query, paint: { 'line-color': '#e3b9a4', 'line-width': 12, 'line-blur': 12, 'line-opacity': 0.2 } },
    { id: 'focus-line', type: 'line', source: SRC.query, paint: { 'line-color': '#e3b9a4', 'line-width': 2, 'line-opacity': 0.9 } },
    {
      id: LAYER.burnFill,
      type: 'fill',
      source: SRC.burns,
      'source-layer': 'contours',
      paint: {
        'fill-color': '#ee8a35',
        'fill-opacity': ['interpolate', ['linear'], ['zoom'], 5, 0.75, SEVERITY_ZOOM, 0.55, SEVERITY_ZOOM + 0.6, 0],
      },
    },
    {
      id: LAYER.severity,
      type: 'fill',
      source: SRC.burns,
      'source-layer': 'severity',
      minzoom: SEVERITY_ZOOM,
      paint: {
        'fill-color': severityColor,
        'fill-opacity': ['interpolate', ['linear'], ['zoom'], SEVERITY_ZOOM, 0, SEVERITY_ZOOM + 0.6, 0.78],
        'fill-antialias': false,
      },
    },
    {
      id: LAYER.burnLine,
      type: 'line',
      source: SRC.burns,
      'source-layer': 'contours',
      minzoom: 7,
      paint: {
        'line-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#ffffff', '#f5e0d5'],
        'line-width': ['case', ['boolean', ['feature-state', 'hover'], false], 2.2, 0.8],
        'line-opacity': 0.85,
      },
    },
    {
      id: LAYER.burnCenters,
      type: 'circle',
      source: SRC.burns,
      'source-layer': 'centers',
      maxzoom: 8.5,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'area_ha']], 0, 2.5, 30, 6, 120, 16],
        'circle-color': '#ee8a35',
        'circle-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.5, 8.5, 0],
        'circle-stroke-color': '#f5e0d5',
        'circle-stroke-width': 1,
        'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.8, 8.5, 0],
      },
    },
    {
      id: LAYER.sources,
      type: 'circle',
      source: SRC.sources,
      layout: { visibility: 'none' },
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['get', 'n_days'], 5, 5, 18, 11],
        'circle-color': 'rgba(143,163,184,0.18)',
        'circle-stroke-color': '#8fa3b8',
        'circle-stroke-width': 1.5,
      },
    },
    {
      id: LAYER.filtered,
      type: 'circle',
      source: SRC.hotspots,
      filter: ['!=', ['get', 'kind'], 'fire'],
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 1.6, 9, 4, 13, 8],
        'circle-color': 'rgba(0,0,0,0)',
        'circle-stroke-color': ['match', ['get', 'kind'], 'glint', '#8ecdf0', '#8fa3b8'],
        'circle-stroke-width': 1.3,
        'circle-stroke-opacity': 0.9,
      },
    },
    {
      id: LAYER.fireGlow,
      type: 'circle',
      source: SRC.hotspots,
      filter: ['==', ['get', 'kind'], 'fire'],
      paint: {
        /*
         * Размер ореола несёт мощность излучения: корень из FRP, чтобы площадь
         * пятна росла с ней линейно. Множитель стоит в точках интерполяции, а не
         * снаружи: MapLibre 6 принимает `zoom` только как вход верхнеуровневого
         * interpolate, и обёрнутое в `*` выражение роняло весь слой.
         */
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          4, ['*', 5, POWER_SCALE],
          9, ['*', 12, POWER_SCALE],
          13, ['*', 26, POWER_SCALE],
        ],
        'circle-color': '#f7774a',
        'circle-blur': 1,
        'circle-opacity': 0.42,
      },
    },
    {
      id: LAYER.firePulse,
      type: 'circle',
      source: SRC.hotspots,
      filter: ['==', ['get', 'id'], -1],
      paint: { 'circle-radius': 10, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#f2cf72', 'circle-stroke-width': 1.5, 'circle-stroke-opacity': 0.8 },
    },
    {
      id: LAYER.fireCore,
      type: 'circle',
      source: SRC.hotspots,
      filter: ['==', ['get', 'kind'], 'fire'],
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 1.4, 9, 3, 13, 6.5],
        'circle-color': ['interpolate', ['linear'], ['get', 'bt_i4'], 320, '#f7774a', 345, '#ffb703', 367, '#fff3b0'],
        'circle-stroke-color': '#2b0d00',
        'circle-stroke-width': 0.6,
      },
    },
    { id: 'zones-line', type: 'line', source: SRC.zones, paint: { 'line-color': '#c1c39c', 'line-width': 1.6, 'line-dasharray': [2, 1.5] } },
  ]
}
