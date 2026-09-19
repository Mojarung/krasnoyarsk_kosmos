import { gsap } from 'gsap'
import { type ExpressionSpecification, type FilterSpecification, type GeoJSONSource, type ImageSource, LngLatBounds, Map as MapLibre, type MapGeoJSONFeature, Marker, Popup, setWorkerUrl, type StyleSpecification } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { FeatureCollection } from 'geojson'
import type { AreaGeometry, FireEventDetail, HotspotCollection, HotspotProps, ResponseCard, SceneSummary, Zone } from '@/lib/types'
import { DEFAULT_FILTERS, type DisplayFilters } from '@/stores/ui'
import { api } from '@/lib/api'
import { fmt } from '@/lib/format'
import type { Coordinates } from '@/lib/inspections'
import { HotspotReveal } from './playback'
import { focusMask, LAYER, loadBaseStyle, type MapTheme, OVERLAY_SOURCES, overlayLayers, SRC } from './style'

setWorkerUrl(workerUrl)

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] }
const INTRO_VIEW = { center: [44, 30] as [number, number], zoom: 1.4 }
const PULSE_WINDOW_S = 3 * 86_400
/** Шаг, с которым при проигрывании проявляются гари: при 50 днях в секунду это около 3 пересборок тайлов в секунду. */
const BURN_STEP_DAYS = 14
const HOTSPOT_LAYERS = [LAYER.fireCore, LAYER.filtered]
const BURN_LAYERS = [LAYER.severity, LAYER.burnFill, LAYER.burnCenters]

export interface TimeWindow {
  fromDay: number
  toDay: number
  playheadTs: number | null
}

export interface MapCallbacks {
  onSceneClick: (sceneId: string) => void
  onHotspotClick: (hotspotId: number) => void
  onInspectionPick: (point: Coordinates) => void
  onDrawn: (geometry: AreaGeometry) => void
}

/** Точки, до которых проигрывание ещё не дошло, лежат на карте прозрачными: наведение и клик их пропускают. */
function isVisible(feature: MapGeoJSONFeature): boolean {
  return !feature.state?.hidden
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}

function hotspotPopup(p: HotspotProps): string {
  const tone = p.kind === 'fire' ? 'var(--fire)' : p.kind === 'glint' ? 'var(--glint)' : 'var(--technogenic)'
  const weather = p.wind_speed == null ? '' : `<div class="text-xs opacity-70">Ветер ${fmt.num(p.wind_speed)} м/с, влажность ${fmt.num(p.rh2m)}%</div>`
  const reason = p.reason ? `<div class="mt-1.5 text-xs leading-snug" style="color:${tone}">${escapeHtml(p.reason)}</div>` : ''
  const power =
    p.frp_mw == null
      ? ''
      : `<div class="mt-1.5 text-xs">Мощность <span class="font-medium">${fmt.num(p.frp_mw)} МВт</span>${p.frp_saturated ? ' <span class="opacity-70">(канал насыщен, оценка снизу)</span>' : ''}</div>`
  return `<div class="text-[13px] min-w-52">
    <div class="flex items-center gap-2 font-medium"><span class="size-2 rounded-full" style="background:${tone}"></span>${escapeHtml(p.kind_label)}</div>
    <div class="mt-1 text-xs opacity-70">${fmt.dateTimeUtc(p.acquired_at)}, ${escapeHtml(p.satellite ?? '')}${p.is_night ? ', ночь' : ''}</div>
    <div class="mt-1.5 grid grid-cols-2 gap-x-3 text-xs"><span>I4 ${fmt.num(p.bt_i4)} K</span><span>I4-I5 ${fmt.num(p.bt_i4 - p.bt_i5)} K</span><span>${escapeHtml(p.landcover)}</span><span>увер. ${fmt.pct(p.confidence)}</span></div>
    ${power}${weather}${reason}${p.kind === 'fire' ? '<div class="mt-2 text-xs">Нажмите, чтобы открыть паспорт пожара</div>' : ''}</div>`
}

export class FireMap {
  readonly map: MapLibre
  private popup = new Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: '300px', className: 'map-hover-tooltip' })
  private hovered: MapGeoJSONFeature | null = null
  private pulse = gsap.timeline({ paused: true, repeat: -1 })
  private draw: { stop: () => void } | null = null
  private window: TimeWindow = { fromDay: 0, toDay: 1e6, playheadTs: null }
  private showFires = true
  private showFiltered = true
  private showSeverity = true
  private eventActive = false
  private inspectionPicking = false
  private inspectionActive = false
  private inspectionMarkers: Marker[] = []
  private destroyed = false
  private themeVersion = 0
  private display: DisplayFilters = DEFAULT_FILTERS
  private satellite = false
  private tilesVersion: number | string = 0
  private clip = ''
  private filters = new Map<string, string>()
  private reveal: HotspotReveal
  ready: Promise<void>

  static async create(container: HTMLElement, theme: MapTheme, background: string, callbacks: MapCallbacks): Promise<FireMap> {
    const instance = new FireMap(container, await loadBaseStyle(theme, background), callbacks)
    await instance.ready
    return instance
  }

  private constructor(
    container: HTMLElement,
    style: StyleSpecification,
    private callbacks: MapCallbacks,
  ) {
    this.map = new MapLibre({
      container,
      style,
      ...INTRO_VIEW,
      minZoom: 1,
      maxZoom: 15,
      attributionControl: { compact: true },
      fadeDuration: 150,
      renderWorldCopies: false,
    })
    this.map.dragRotate.disable()
    this.map.touchZoomRotate.disableRotation()
    this.reveal = new HotspotReveal(this.map, SRC.hotspots, PULSE_WINDOW_S)
    this.ready = new Promise((resolve) => this.map.once('load', () => resolve(this.setup())))
  }

  private setup() {
    const map = this.map
    const colors = this.eventColors()
    for (const id of [SRC.aoi, SRC.regions, SRC.focus, SRC.query, SRC.hotspots, SRC.sources, SRC.zones, SRC.event, SRC.spread]) {
      map.addSource(id, { type: 'geojson', data: EMPTY })
    }
    map.addSource(SRC.burns, { type: 'vector', tiles: [this.tileUrl(0)], minzoom: 3, maxzoom: 11 })
    for (const layer of overlayLayers()) map.addLayer(layer)
    map.addLayer({ id: 'event-burn', type: 'fill', source: SRC.event, filter: ['==', ['get', 'kind'], 'burn'], paint: {
      'fill-color': ['match', ['get', 'severity'], 1, colors.sev1, 2, colors.sev2, colors.sev3], 'fill-opacity': 0.78,
    } })
    map.addLayer({ id: 'event-outline', type: 'line', source: SRC.event, filter: ['==', ['get', 'kind'], 'burn'], paint: { 'line-color': colors.outline, 'line-width': 0.5, 'line-opacity': 0.5 } })
    map.addLayer({ id: 'event-hotspot', type: 'circle', source: SRC.event, filter: ['==', ['get', 'kind'], 'hotspot'], paint: { 'circle-color': colors.fire, 'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 2, 10, 3, 13, 5], 'circle-stroke-color': colors.stroke, 'circle-stroke-width': 1 } })

    const pulse = { radius: 4, opacity: 0.9 }
    this.pulse.to(pulse, {
      radius: 22,
      opacity: 0,
      duration: 1.3,
      ease: 'power2.out',
      onUpdate: () => {
        map.setPaintProperty(LAYER.firePulse, 'circle-radius', pulse.radius)
        map.setPaintProperty(LAYER.firePulse, 'circle-stroke-opacity', pulse.opacity)
      },
    })

    map.on('mousemove', (e) => this.handleHover(e.point))
    map.on('mouseout', () => this.clearHover())
    map.on('click', (e) => {
      if (this.draw) return
      if (this.inspectionPicking) {
        this.callbacks.onInspectionPick([Number(e.lngLat.lng.toFixed(6)), Number(e.lngLat.lat.toFixed(6))])
        return
      }
      if (this.inspectionActive) return
      const hotspot = map.queryRenderedFeatures(e.point, { layers: ['event-hotspot', LAYER.fireCore] }).find(isVisible)
      if (hotspot?.properties?.id != null) {
        this.clearHover()
        this.callbacks.onHotspotClick(Number(hotspot.properties.id))
        return
      }
      const hit = map.queryRenderedFeatures(e.point, { layers: BURN_LAYERS })[0]
      const sceneId = hit?.properties?.scene_id
      if (typeof sceneId === 'string') {
        this.clearHover()
        this.callbacks.onSceneClick(sceneId)
      }
    })
  }

  private tileUrl(version: number | string): string {
    const clip = this.clip ? `&clip=${encodeURIComponent(this.clip)}` : ''
    return `${window.location.origin}/api/v1/tiles/burns/{z}/{x}/{y}.mvt?v=${version}${clip}`
  }

  private reloadTiles() {
    const source = this.map.getSource(SRC.burns)
    if (source && 'setTiles' in source) (source as unknown as { setTiles: (t: string[]) => void }).setTiles([this.tileUrl(this.tilesVersion)])
  }

  /** Гари вне выбранной области не приходят с сервера: ключ области входит в адрес тайла. */
  setClip(clip: string) {
    if (clip === this.clip) return
    this.clip = clip
    this.reloadTiles()
  }

  private handleHover(point: { x: number; y: number }) {
    if (this.draw || this.inspectionPicking) return
    const map = this.map
    const hotspot = map.queryRenderedFeatures([point.x, point.y] as [number, number], { layers: HOTSPOT_LAYERS }).find(isVisible)
    const burn = hotspot ? undefined : map.queryRenderedFeatures([point.x, point.y] as [number, number], { layers: BURN_LAYERS })[0]
    map.getCanvas().style.cursor = hotspot || burn ? 'pointer' : ''

    if (this.hovered && this.hovered.id !== burn?.id) this.setHoverState(this.hovered, false)
    if (hotspot) {
      const coordinates = (hotspot.geometry as GeoJSON.Point).coordinates as [number, number]
      this.popup.setLngLat(coordinates).setHTML(hotspotPopup(hotspot.properties as HotspotProps)).addTo(map)
      return
    }
    if (burn && burn.id != null) {
      this.hovered = burn
      this.setHoverState(burn, true)
      const p = burn.properties
      const title = p.severity ? `Степень: ${['', 'слабая', 'средняя', 'сильная'][p.severity]}` : 'Контур гари'
      this.popup
        .setLngLat(map.unproject([point.x, point.y]))
        .setHTML(`<div class="text-[13px]"><div class="font-medium">${title}</div><div class="text-xs opacity-70 mt-0.5">${fmt.ha(p.area_ha)} га, нажмите, чтобы открыть паспорт</div></div>`)
        .addTo(map)
      return
    }
    this.popup.remove()
  }

  private setHoverState(feature: MapGeoJSONFeature, hover: boolean) {
    const id = feature.properties?.contour_id ?? feature.id
    if (id != null) this.map.setFeatureState({ source: SRC.burns, sourceLayer: 'contours', id }, { hover })
    if (!hover) this.hovered = null
  }

  private clearHover() {
    if (this.hovered) this.setHoverState(this.hovered, false)
    this.popup.remove()
  }

  private geojson(id: string): GeoJSONSource {
    return this.map.getSource(id) as GeoJSONSource
  }

  setStatic(aoi: GeoJSON.Feature, regions: FeatureCollection) {
    this.geojson(SRC.aoi).setData(aoi)
    this.geojson(SRC.regions).setData(regions)
  }

  setFocus(geometry: AreaGeometry, animate = true) {
    const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
    this.geojson(SRC.focus).setData(focusMask(polygons.map((rings) => rings[0])))
    this.geojson(SRC.query).setData({ type: 'Feature', properties: {}, geometry })

    const bounds = new LngLatBounds()
    for (const rings of polygons) for (const [lon, lat] of rings[0]) bounds.extend([lon, lat])
    const wide = window.innerWidth >= 1024
    this.map.fitBounds(bounds, {
      padding: wide ? { left: 400, right: 460, top: 100, bottom: 190 } : { left: 24, right: 24, top: 90, bottom: 220 },
      duration: animate ? 2200 : 0,
      curve: 1.5,
      essential: true,
    })
  }

  flyTo(lon: number, lat: number, zoom = 11) {
    this.map.flyTo({ center: [lon, lat], zoom, duration: 1800, curve: 1.4, essential: true })
  }

  setHotspots(collection: HotspotCollection) {
    this.geojson(SRC.hotspots).setData(collection)
    this.reveal.setData(collection)
  }

  showEvent(event: FireEventDetail | null) {
    this.clearHover()
    this.eventActive = !!event
    this.applyVisibility()
    this.geojson(SRC.event).setData(event?.map ?? EMPTY)
    if (!event?.bbox) return
    const [west, south, east, north] = event.bbox
    const mobile = window.innerWidth < 640
    this.map.fitBounds([[west, south], [east, north]], {
      padding: mobile ? { left: 25, right: 25, top: 85, bottom: Math.round(window.innerHeight * 0.72) } : { left: 50, right: 490, top: 100, bottom: 80 },
      maxZoom: 12, duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 800,
    })
  }

  setInspection(picking: boolean, site: Coordinates | null, access: Coordinates | null, active: boolean) {
    this.inspectionPicking = picking
    this.inspectionActive = active
    this.map.getCanvas().style.cursor = picking ? 'crosshair' : ''
    this.clearHover()
    for (const marker of this.inspectionMarkers) marker.remove()
    this.inspectionMarkers = []
    for (const [point, label] of [[site, '1'], [access, '2']] as const) {
      if (!point) continue
      const element = document.createElement('div')
      element.className = 'inspection-marker'
      element.textContent = label
      element.setAttribute('aria-label', label === '1' ? 'Место осмотра' : 'Место остановки')
      this.inspectionMarkers.push(new Marker({ element }).setLngLat(point).addTo(this.map))
    }
  }

  setSources(collection: FeatureCollection, visible: boolean) {
    this.geojson(SRC.sources).setData(collection)
    this.map.setLayoutProperty(LAYER.sources, 'visibility', visible ? 'visible' : 'none')
  }

  setZones(zones: Zone[]) {
    this.geojson(SRC.zones).setData({
      type: 'FeatureCollection',
      features: zones.map((z) => ({ type: 'Feature', properties: { name: z.name }, geometry: z.geometry })),
    })
  }

  /** Прогноз фронта выбранного очага: эллипсы на 1, 3 и 6 часов, сёла под угрозой и ближайшая пожарная часть. */
  setSpread(card: ResponseCard | null) {
    if (!card) {
      this.geojson(SRC.spread).setData(EMPTY)
      return
    }
    const point = (lon: number, lat: number, role: string, label: string): GeoJSON.Feature => ({
      type: 'Feature',
      properties: { role, label },
      geometry: { type: 'Point', coordinates: [lon, lat] },
    })
    // Дальний горизонт рисуется первым, иначе он закроет ближние.
    const ellipses = [...card.spread.ellipses].reverse().map((e): GeoJSON.Feature => ({ type: 'Feature', properties: { hours: e.hours }, geometry: e.geometry }))
    const threats = (card.threats ?? []).filter((t) => t.horizon_h != null).map((t) => point(t.lon, t.lat, 'threat', t.name))
    const station = card.arrival ? [point(card.arrival.lon, card.arrival.lat, 'station', card.arrival.station)] : []
    this.geojson(SRC.spread).setData({ type: 'FeatureCollection', features: [...ellipses, ...threats, ...station] })

    const bounds = new LngLatBounds([card.lon, card.lat], [card.lon, card.lat])
    for (const e of card.spread.ellipses) for (const [lon, lat] of e.geometry.coordinates[0]) bounds.extend([lon, lat])
    this.map.fitBounds(bounds, { padding: { left: 80, right: 480, top: 120, bottom: 200 }, maxZoom: 12, duration: 1600, essential: true })
  }

  setBasemap(basemap: 'dark' | 'satellite') {
    this.satellite = basemap === 'satellite'
    this.map.setLayoutProperty(SRC.basemapSat, 'visibility', this.satellite ? 'visible' : 'none')
  }

  private eventColors() {
    const css = getComputedStyle(document.documentElement)
    const token = (name: string) => css.getPropertyValue(name).trim()
    return { sev1: token('--sev-1'), sev2: token('--sev-2'), sev3: token('--sev-3'), fire: token('--fire'), outline: token('--primary'), stroke: token('--foreground') }
  }

  private refreshEventColors() {
    if (!this.map.getLayer('event-burn')) return
    const c = this.eventColors()
    this.map.setPaintProperty('event-burn', 'fill-color', ['match', ['get', 'severity'], 1, c.sev1, 2, c.sev2, c.sev3])
    this.map.setPaintProperty('event-outline', 'line-color', c.outline)
    this.map.setPaintProperty('event-hotspot', 'circle-color', c.fire)
    this.map.setPaintProperty('event-hotspot', 'circle-stroke-color', c.stroke)
  }

  async setTheme(theme: MapTheme, background: string) {
    const version = ++this.themeVersion
    const next = await loadBaseStyle(theme, background)
    if (this.destroyed || version !== this.themeVersion) return
    this.map.setStyle(next, {
      transformStyle: (previous, style) => {
        if (!previous) return style
        const sources = Object.fromEntries(Object.entries(previous.sources).filter(([id]) => OVERLAY_SOURCES.has(id)))
        const layers = previous.layers.filter((layer) => 'source' in layer && OVERLAY_SOURCES.has(layer.source))
        return { ...style, sources: { ...style.sources, ...sources }, layers: [...style.layers, ...layers] }
      },
    })
    this.map.once('styledata', () => {
      this.setBasemap(this.satellite ? 'satellite' : 'dark')
      this.refreshEventColors()
    })
  }

  setLayerToggles(showFires: boolean, showFiltered: boolean, showSeverity: boolean) {
    this.showFires = showFires
    this.showFiltered = showFiltered
    this.showSeverity = showSeverity
    this.applyVisibility()
    this.applyTime()
  }

  /* Паспорт пожара рисует собственные слои, поэтому обзорные на это время
     гасятся целиком, независимо от переключателей слоёв. */
  private applyVisibility() {
    const shown = (on: boolean) => (on && !this.eventActive ? 'visible' : 'none')
    for (const id of [LAYER.severity, LAYER.burnFill, LAYER.burnLine, LAYER.burnCenters]) {
      this.map.setLayoutProperty(id, 'visibility', shown(this.showSeverity))
    }
    for (const id of [LAYER.fireGlow, LAYER.fireCore, LAYER.firePulse]) {
      this.map.setLayoutProperty(id, 'visibility', shown(this.showFires))
    }
    this.map.setLayoutProperty(LAYER.filtered, 'visibility', shown(this.showFiltered))
  }

  setTimeWindow(next: TimeWindow) {
    this.window = next
    this.applyTime()
  }

  setDisplayFilters(next: DisplayFilters) {
    this.display = next
    this.applyTime()
  }

  private applyTime() {
    const { fromDay, toDay, playheadTs } = this.window
    const { severities, minContourHa, dayNight, minConfidence, satellites } = this.display
    const playing = playheadTs != null
    // Гари при проигрывании проявляются шагами: смена фильтра пересобирает все векторные тайлы гарей.
    const playDay = playing ? Math.floor(playheadTs / 86_400) : toDay
    const lastDay = playing ? Math.min(toDay, fromDay + Math.floor((playDay - fromDay) / BURN_STEP_DAYS) * BURN_STEP_DAYS) : toDay
    const inPeriod: ExpressionSpecification = ['all', ['<=', ['get', playing ? 't1' : 't0'], lastDay], ['>=', ['get', 't1'], fromDay]]

    const hasSeverity: ExpressionSpecification = ['any', ...severities.map((k): ExpressionSpecification => ['>', ['get', `sev${k}_ha`], 0])]
    const contourFilter: ExpressionSpecification = ['all', inPeriod, ['>=', ['get', 'area_ha'], minContourHa], ...(severities.length < 3 ? [hasSeverity] : [])]
    for (const id of [LAYER.burnFill, LAYER.burnLine]) this.setFilterOnce(id, contourFilter)
    this.setFilterOnce(LAYER.burnCenters, ['all', inPeriod, ['>=', ['get', 'area_ha'], minContourHa]])
    this.setFilterOnce(LAYER.severity, ['all', inPeriod, ['in', ['get', 'severity'], ['literal', severities]], ['>=', ['get', 'contour_ha'], minContourHa]])

    // Время в фильтры точек не входит: день проигрывания открывает точки через feature-state.
    const common: ExpressionSpecification[] = []
    if (dayNight !== 'all') common.push(['==', ['get', 'is_night'], dayNight === 'night'])
    if (satellites.length) common.push(['in', ['get', 'satellite'], ['literal', satellites]])
    const fire: ExpressionSpecification = ['all', ['==', ['get', 'kind'], 'fire'], ['>=', ['get', 'confidence'], minConfidence], ...common]
    this.setFilterOnce(LAYER.fireCore, fire)
    this.setFilterOnce(LAYER.fireGlow, fire)
    this.setFilterOnce(LAYER.filtered, this.showFiltered ? ['all', ['!=', ['get', 'kind'], 'fire'], ...common] : ['literal', false])
    this.setFilterOnce(LAYER.firePulse, playing ? fire : ['literal', false])
    this.reveal.seek(playheadTs)

    if (playing) this.pulse.play()
    else this.pulse.pause(0)
  }

  /** Повторный setFilter с тем же выражением всё равно пересобирает тайлы, поэтому одинаковые пропускаются. */
  private setFilterOnce(id: string, filter: FilterSpecification) {
    const key = JSON.stringify(filter)
    if (this.filters.get(id) === key) return
    this.filters.set(id, key)
    this.map.setFilter(id, filter)
  }

  refreshTiles(version: number | string) {
    this.tilesVersion = version
    this.reloadTiles()
  }

  showScene(scene: SceneSummary | null, quicklook: string) {
    const map = this.map
    if (!scene?.corners) {
      if (map.getLayer(LAYER.scene)) map.setPaintProperty(LAYER.scene, 'raster-opacity', 0)
      return
    }
    const coordinates = scene.corners as [[number, number], [number, number], [number, number], [number, number]]
    const url = api.quicklookUrl(scene.id, quicklook)
    const existing = map.getSource(SRC.scene) as ImageSource | undefined
    if (existing) {
      existing.updateImage({ url, coordinates })
    } else {
      map.addSource(SRC.scene, { type: 'image', url, coordinates })
      map.addLayer({ id: LAYER.scene, type: 'raster', source: SRC.scene, paint: { 'raster-opacity': 0, 'raster-opacity-transition': { duration: 500 }, 'raster-fade-duration': 0 } }, LAYER.burnFill)
    }
    map.setPaintProperty(LAYER.scene, 'raster-opacity', 0.95)
    const bounds = coordinates.reduce((b, c) => b.extend(c), new LngLatBounds())
    map.fitBounds(bounds, { padding: { left: 60, right: 60, top: 100, bottom: 120 }, duration: 1600, essential: true })
  }

  async startDraw(mode: 'polygon' | 'rectangle') {
    this.stopDraw()
    this.clearHover()
    const { beginDraw } = await import('./draw')
    this.draw = beginDraw(this.map, mode, (geometry) => {
      this.stopDraw()
      this.callbacks.onDrawn(geometry)
    })
  }

  stopDraw() {
    this.draw?.stop()
    this.draw = null
  }

  destroy() {
    this.destroyed = true
    this.pulse.kill()
    this.stopDraw()
    this.map.remove()
  }
}
