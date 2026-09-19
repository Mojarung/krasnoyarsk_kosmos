<script setup lang="ts">
import { Map as MapLibre, type GeoJSONSource, type MapMouseEvent, type ExpressionSpecification } from 'maplibre-gl'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { FireMap } from './controller'
import { OVERLAY_SOURCES } from './style'
import { useSpatialStore } from '@/stores/spatial'
import { WORK_COLORS, type WorkProps } from '@/lib/work-map'

const props = defineProps<{ owner: FireMap }>()
const spatial = useSpatialStore()
const container = ref<HTMLElement | null>(null)
const map = props.owner.map
const ids = ['work-zone', 'work-selected', 'visual-recent']
let secondary: MapLibre | null = null
let disposed = false
let epoch = 0
let saved: { center: [number, number]; zoom: number; bearing: number; pitch: number; padding: ReturnType<MapLibre['getPadding']> } | null = null
let projection = map.getProjection() ?? { type: 'globe' as const }
const savedVisibility = new Map<string, 'none' | 'visible'>()
const hidden = ['event-burn', 'event-hotspot']
const empty = { type: 'FeatureCollection' as const, features: [] }

function hideEvent() {
  for (const id of hidden) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none')
}
function sync() {
  if (secondary) secondary.jumpTo({ center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: 0, padding: map.getPadding() })
}
function resize() { secondary?.resize(); sync() }
function remove() {
  secondary?.remove(); secondary = null
  if (props.owner.isDestroyed) return
  for (const id of ['work-selected-line', 'work-hatch', 'work-line', 'work-fill', 'visual-recent-layer']) if (map.getLayer(id)) map.removeLayer(id)
  for (const id of ids) if (map.getSource(id)) map.removeSource(id)
}
function pattern(name: string, spacing: number, cross = false) {
  if (map.hasImage(name)) return
  const data = new Uint8Array(8 * 8 * 4)
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    const i = (y * 8 + x) * 4
    if ((x + y) % spacing === 0 || (cross && (x - y + 8) % spacing === 0)) data.set([248, 240, 219, 145], i)
  }
  map.addImage(name, { width: 8, height: 8, data })
}
function workLayers() {
  const data = spatial.work?.map
  if (!data) return
  map.addSource('work-zone', { type: 'geojson', data })
  const color = ['match', ['get', 'action'], ...Object.entries(WORK_COLORS).flat(), '#888b8a'] as unknown as ExpressionSpecification
  map.addLayer({ id: 'work-fill', type: 'fill', source: 'work-zone', paint: { 'fill-color': color, 'fill-opacity': 0.82 } })
  map.addLayer({ id: 'work-line', type: 'line', source: 'work-zone', paint: { 'line-color': '#f5e0d5', 'line-opacity': 0.4, 'line-width': 0.6 } })
  pattern('work-agro', 8); pattern('work-erosion', 4); pattern('work-unknown', 8, true)
  map.addLayer({ id: 'work-hatch', type: 'fill', source: 'work-zone', filter: ['in', ['get', 'action'], ['literal', ['agro', 'erosion', 'unknown']]], paint: { 'fill-pattern': ['concat', 'work-', ['get', 'action']], 'fill-opacity': 0.85 } })
  map.addSource('work-selected', { type: 'geojson', data: empty })
  map.addLayer({ id: 'work-selected-line', type: 'line', source: 'work-selected', paint: { 'line-color': '#fff4e8', 'line-width': 3 } })
  selectOutline()
}
function selectOutline() {
  const feature = spatial.work?.map?.features.find(f => f.properties.id === spatial.selected?.properties.id)
  ;(map.getSource('work-selected') as GeoJSONSource | undefined)?.setData(feature ?? empty)
}
function click(e: MapMouseEvent) {
  if (spatial.mode !== 'works' || !map.getLayer('work-fill')) return
  const feature = map.queryRenderedFeatures(e.point, { layers: ['work-fill'] })[0]
  spatial.selected = feature ? { properties: feature.properties as WorkProps, point: [e.lngLat.lng, e.lngLat.lat] } : null
}
function hover(e: MapMouseEvent) {
  if (spatial.mode === 'works' && map.getLayer('work-fill')) map.getCanvas().style.cursor = map.queryRenderedFeatures(e.point, { layers: ['work-fill'] }).length ? 'pointer' : ''
}
async function loadImage(url: string) {
  await new Promise<void>((resolve, reject) => { const image = new Image(); image.onload = () => resolve(); image.onerror = reject; image.src = url })
}
async function render() {
  const current = ++epoch
  if (disposed) return
  remove(); hideEvent()
  if (spatial.mode === 'works') { workLayers(); return }
  const report = spatial.comparison
  if (!spatial.pairReady || !report?.georef || !report.post_fire?.rgb_url || !report.recent?.rgb_url) return
  try { await Promise.all([loadImage(report.post_fire.rgb_url), loadImage(report.recent.rgb_url)]) }
  catch { if (current === epoch && !disposed) spatial.imageError = 'Не удалось загрузить изображения'; return }
  if (current !== epoch || disposed) return
  spatial.imageError = ''
  const coordinates = report.georef.corners
  map.addSource('visual-recent', { type: 'image', url: report.recent.rgb_url, coordinates })
  map.addLayer({ id: 'visual-recent-layer', type: 'raster', source: 'visual-recent', paint: { 'raster-fade-duration': 0 } }, 'event-outline')
  const eventData = spatial.event?.map ?? empty
  secondary = new MapLibre({ container: container.value!, interactive: false, attributionControl: false,
    center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: 0,
    renderWorldCopies: false, fadeDuration: 0,
    style: { version: 8, projection: { type: 'mercator' }, sources: {
      before: { type: 'image', url: report.post_fire.rgb_url, coordinates },
      outline: { type: 'geojson', data: eventData },
    }, layers: [
      { id: 'before', type: 'raster', source: 'before', paint: { 'raster-fade-duration': 0 } },
      { id: 'outline', type: 'line', source: 'outline', filter: ['==', ['get', 'kind'], 'burn'], paint: { 'line-color': '#f5e0d5', 'line-width': 0.6 } },
    ] },
  })
  secondary.jumpTo({ padding: map.getPadding() })
  secondary.on('load', sync)
}
function styleChanged() {
  map.setProjection({ type: 'mercator' })
  hideEvent()
  for (const [name, spacing, cross] of [['work-agro', 8, false], ['work-erosion', 4, false], ['work-unknown', 8, true]] as const) pattern(name, spacing, cross)
}
onMounted(() => {
  props.owner.spatialActive = true
  for (const id of ids) OVERLAY_SOURCES.add(id)
  saved = { center: map.getCenter().toArray() as [number, number], zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch(), padding: map.getPadding() }
  projection = map.getProjection() ?? { type: 'globe' }
  for (const id of hidden) savedVisibility.set(id, (map.getLayoutProperty(id, 'visibility') as 'none' | 'visible') ?? 'visible')
  map.setProjection({ type: 'mercator' }); map.jumpTo({ bearing: 0, pitch: 0 })
  const bounds = spatial.event?.bbox
  if (bounds) map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: { top: 190, bottom: 90, left: 45, right: 45 }, maxZoom: 13, duration: 0 })
  map.on('move', sync); map.on('resize', resize); map.on('click', click); map.on('mousemove', hover); map.on('style.load', styleChanged)
  void render()
})
watch([() => spatial.work, () => spatial.comparison], () => void render())
watch(() => spatial.selected, selectOutline)
onBeforeUnmount(() => {
  disposed = true; epoch++
  map.off('move', sync); map.off('resize', resize); map.off('click', click); map.off('mousemove', hover); map.off('style.load', styleChanged)
  remove()
  for (const id of ids) OVERLAY_SOURCES.delete(id)
  if (props.owner.isDestroyed) return
  for (const [id, visibility] of savedVisibility) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visibility)
  map.getCanvas().style.cursor = ''
  props.owner.spatialActive = false
  map.setProjection(projection)
  if (saved) map.jumpTo(saved)
})
</script>

<template>
  <div class="pointer-events-none absolute inset-0 z-[1]" :style="{ clipPath: `inset(0 ${100 - spatial.split}% 0 0)` }" aria-hidden="true"><div ref="container" class="size-full" /></div>
</template>
