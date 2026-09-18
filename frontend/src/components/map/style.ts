import type { AddLayerObject, ExpressionSpecification, StyleSpecification } from 'maplibre-gl'

export const SRC = {
  basemapDark: 'basemap-dark',
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

export const SEVERITY_ZOOM = 9
const FOCUS_BOUNDS = [
  [15, 30],
  [80, 30],
  [80, 68],
  [15, 68],
  [15, 30],
]

export function focusMask(rings: number[][][]): GeoJSON.Feature<GeoJSON.Polygon> {
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [FOCUS_BOUNDS, ...rings] } }
}

export function baseStyle(background: string): StyleSpecification {
  return {
    version: 8,
    projection: { type: 'globe' },
    sky: {
      'sky-color': '#0b0a12',
      'horizon-color': '#2a1a12',
      'fog-color': '#120f0d',
      'sky-horizon-blend': 0.6,
      'horizon-fog-blend': 0.8,
      'fog-ground-blend': 0.9,
      'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 0.6, 7, 0],
    },
    sources: {
      [SRC.basemapDark]: {
        type: 'raster',
        tiles: ['a', 'b', 'c', 'd'].map((s) => `https://${s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png`),
        tileSize: 256,
        maxzoom: 19,
        attribution: '© OpenStreetMap, © CARTO',
      },
      [SRC.basemapSat]: {
        type: 'raster',
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        tileSize: 256,
        maxzoom: 18,
        attribution: 'Esri, Maxar, Earthstar Geographics',
      },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': background } },
      { id: SRC.basemapDark, type: 'raster', source: SRC.basemapDark, paint: { 'raster-opacity': 1, 'raster-fade-duration': 250 } },
      {
        id: SRC.basemapSat,
        type: 'raster',
        source: SRC.basemapSat,
        layout: { visibility: 'none' },
        paint: { 'raster-saturation': -0.25, 'raster-brightness-max': 0.82 },
      },
    ],
  }
}

const severityColor: ExpressionSpecification = ['match', ['get', 'severity'], 1, '#ffd166', 2, '#f77f00', 3, '#d00000', '#f77f00']

export function overlayLayers(): AddLayerObject[] {
  return [
    { id: 'focus-mask', type: 'fill', source: SRC.focus, paint: { 'fill-color': '#0a0807', 'fill-opacity': 0.58, 'fill-opacity-transition': { duration: 600 } } },
    { id: 'regions-line', type: 'line', source: SRC.regions, paint: { 'line-color': '#f0dfd6', 'line-opacity': 0.16, 'line-width': 1 } },
    { id: 'aoi-line', type: 'line', source: SRC.aoi, paint: { 'line-color': '#ffb693', 'line-opacity': 0.5, 'line-width': 1.4, 'line-dasharray': [3, 2] } },
    { id: 'focus-line', type: 'line', source: SRC.query, paint: { 'line-color': '#ffb693', 'line-width': 2, 'line-opacity': 0.9 } },
    {
      id: LAYER.burnFill,
      type: 'fill',
      source: SRC.burns,
      'source-layer': 'contours',
      paint: {
        'fill-color': '#f77f00',
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
        'line-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#ffffff', '#ffdbca'],
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
        'circle-color': '#f77f00',
        'circle-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.5, 8.5, 0],
        'circle-stroke-color': '#ffdbca',
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
        'circle-stroke-color': ['match', ['get', 'kind'], 'glint', '#7dd3fc', '#8fa3b8'],
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
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 5, 9, 12, 13, 26],
        'circle-color': '#ff6b35',
        'circle-blur': 1,
        'circle-opacity': 0.42,
      },
    },
    {
      id: LAYER.firePulse,
      type: 'circle',
      source: SRC.hotspots,
      filter: ['==', ['get', 'id'], -1],
      paint: { 'circle-radius': 10, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#ffd166', 'circle-stroke-width': 1.5, 'circle-stroke-opacity': 0.8 },
    },
    {
      id: LAYER.fireCore,
      type: 'circle',
      source: SRC.hotspots,
      filter: ['==', ['get', 'kind'], 'fire'],
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 1.4, 9, 3, 13, 6.5],
        'circle-color': ['interpolate', ['linear'], ['get', 'bt_i4'], 320, '#ff6b35', 345, '#ffb703', 367, '#fff3b0'],
        'circle-stroke-color': '#2b0d00',
        'circle-stroke-width': 0.6,
      },
    },
    { id: 'zones-line', type: 'line', source: SRC.zones, paint: { 'line-color': '#c9ca94', 'line-width': 1.6, 'line-dasharray': [2, 1.5] } },
  ]
}
