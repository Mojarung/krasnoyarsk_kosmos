import { gsap } from 'gsap'
import { type FilterSpecification, type GeoJSONSource, type ImageSource, LngLatBounds, Map as MapLibre, type MapGeoJSONFeature, Popup, setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { FeatureCollection } from 'geojson'
import type { AreaGeometry, HotspotCollection, HotspotProps, SceneSummary, Zone } from '@/lib/types'
import { api } from '@/lib/api'
import { fmt } from '@/lib/format'
import { baseStyle, focusMask, LAYER, overlayLayers, SRC } from './style'

setWorkerUrl(workerUrl)

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] }
const INTRO_VIEW = { center: [44, 30] as [number, number], zoom: 1.4 }
const PULSE_WINDOW_S = 3 * 86_400
const HOTSPOT_LAYERS = [LAYER.fireCore, LAYER.filtered]
const BURN_LAYERS = [LAYER.severity, LAYER.burnFill, LAYER.burnCenters]

export interface TimeWindow {
  fromDay: number
  toDay: number
  playheadTs: number | null
}

export interface MapCallbacks {
  onSceneClick: (sceneId: string) => void
  onDrawn: (geometry: AreaGeometry) => void
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}

function hotspotPopup(p: HotspotProps): string {
  const tone = p.kind === 'fire' ? 'var(--fire)' : p.kind === 'glint' ? 'var(--glint)' : 'var(--technogenic)'
  const weather = p.wind_speed == null ? '' : `<div class="text-xs opacity-70">Ветер ${fmt.num(p.wind_speed)} м/с, влажность ${fmt.num(p.rh2m)}%</div>`
  const reason = p.reason ? `<div class="mt-1.5 text-xs leading-snug" style="color:${tone}">${escapeHtml(p.reason)}</div>` : ''
  return `<div class="text-[13px] min-w-52">
    <div class="flex items-center gap-2 font-medium"><span class="size-2 rounded-full" style="background:${tone}"></span>${escapeHtml(p.kind_label)}</div>
    <div class="mt-1 text-xs opacity-70">${fmt.dateTimeUtc(p.acquired_at)} · ${escapeHtml(p.satellite ?? '')}${p.is_night ? ' · ночь' : ''}</div>
    <div class="mt-1.5 grid grid-cols-2 gap-x-3 text-xs"><span>I4 ${fmt.num(p.bt_i4)} K</span><span>I4-I5 ${fmt.num(p.bt_i4 - p.bt_i5)} K</span><span>${escapeHtml(p.landcover)}</span><span>увер. ${fmt.pct(p.confidence)}</span></div>
    ${weather}${reason}</div>`
}

export class FireMap {
  readonly map: MapLibre
  private popup = new Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: '300px' })
  private hovered: MapGeoJSONFeature | null = null
  private pulse = gsap.timeline({ paused: true, repeat: -1 })
  private draw: { stop: () => void } | null = null
  private window: TimeWindow = { fromDay: 0, toDay: 1e6, playheadTs: null }
  private showFiltered = true
  ready: Promise<void>

  constructor(
    container: HTMLElement,
    background: string,
    private callbacks: MapCallbacks,
  ) {
    this.map = new MapLibre({
      container,
      style: baseStyle(background),
      ...INTRO_VIEW,
      minZoom: 1,
      maxZoom: 15,
      attributionControl: { compact: true },
      fadeDuration: 150,
      renderWorldCopies: false,
    })
    this.map.dragRotate.disable()
    this.map.touchZoomRotate.disableRotation()
    this.ready = new Promise((resolve) => this.map.once('load', () => resolve(this.setup())))
  }

  private setup() {
    const map = this.map
    for (const id of [SRC.aoi, SRC.regions, SRC.focus, SRC.query, SRC.hotspots, SRC.sources, SRC.zones]) {
      map.addSource(id, { type: 'geojson', data: EMPTY })
    }
    map.addSource(SRC.burns, { type: 'vector', tiles: [this.tileUrl(0)], minzoom: 3, maxzoom: 13 })
    for (const layer of overlayLayers()) map.addLayer(layer)

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
      const hit = map.queryRenderedFeatures(e.point, { layers: BURN_LAYERS })[0]
      const sceneId = hit?.properties?.scene_id
      if (typeof sceneId === 'string') this.callbacks.onSceneClick(sceneId)
    })
  }

  private tileUrl(version: number): string {
    return `${window.location.origin}/api/v1/tiles/burns/{z}/{x}/{y}.mvt?v=${version}`
  }

  private handleHover(point: { x: number; y: number }) {
    if (this.draw) return
    const map = this.map
    const hotspot = map.queryRenderedFeatures([point.x, point.y] as [number, number], { layers: HOTSPOT_LAYERS })[0]
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
        .setHTML(`<div class="text-[13px]"><div class="font-medium">${title}</div><div class="text-xs opacity-70 mt-0.5">${fmt.ha(p.area_ha)} га · нажмите, чтобы сравнить до/после</div></div>`)
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

  setBasemap(basemap: 'dark' | 'satellite') {
    this.map.setLayoutProperty(SRC.basemapSat, 'visibility', basemap === 'satellite' ? 'visible' : 'none')
    this.map.setLayoutProperty(SRC.basemapDark, 'visibility', basemap === 'dark' ? 'visible' : 'none')
  }

  setLayerToggles(showFiltered: boolean, showSeverity: boolean) {
    this.showFiltered = showFiltered
    for (const id of [LAYER.severity, LAYER.burnFill, LAYER.burnLine, LAYER.burnCenters]) {
      this.map.setLayoutProperty(id, 'visibility', showSeverity ? 'visible' : 'none')
    }
    this.applyTime()
  }

  setTimeWindow(next: TimeWindow) {
    this.window = next
    this.applyTime()
  }

  private applyTime() {
    const { fromDay, toDay, playheadTs } = this.window
    const lastDay = playheadTs == null ? toDay : Math.min(toDay, Math.floor(playheadTs / 86_400))
    const burnFilter: FilterSpecification = ['all', ['<=', ['get', playheadTs == null ? 't0' : 't1'], lastDay], ['>=', ['get', 't1'], fromDay]]
    for (const id of [LAYER.severity, LAYER.burnFill, LAYER.burnLine, LAYER.burnCenters]) this.map.setFilter(id, burnFilter)

    const until: FilterSpecification = playheadTs == null ? ['literal', true] : ['<=', ['get', 'ts'], playheadTs]
    const isFire: FilterSpecification = ['==', ['get', 'kind'], 'fire']
    this.map.setFilter(LAYER.fireCore, ['all', isFire, until])
    this.map.setFilter(LAYER.fireGlow, ['all', isFire, until])
    this.map.setFilter(LAYER.filtered, this.showFiltered ? ['all', ['!=', ['get', 'kind'], 'fire'], until] : ['literal', false])

    if (playheadTs == null) {
      this.pulse.pause(0)
      this.map.setFilter(LAYER.firePulse, ['literal', false])
    } else {
      this.map.setFilter(LAYER.firePulse, ['all', isFire, ['<=', ['get', 'ts'], playheadTs], ['>', ['get', 'ts'], playheadTs - PULSE_WINDOW_S]])
      this.pulse.play()
    }
  }

  refreshTiles(version: number) {
    const source = this.map.getSource(SRC.burns)
    if (source && 'setTiles' in source) (source as unknown as { setTiles: (t: string[]) => void }).setTiles([this.tileUrl(version)])
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
    this.pulse.kill()
    this.stopDraw()
    this.map.remove()
  }
}
