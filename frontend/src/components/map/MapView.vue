<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { api } from '@/lib/api'
import { dayNumber } from '@/lib/format'
import type { SceneSummary } from '@/lib/types'
import { useLiveStore } from '@/stores/live'
import { AOI_REGION_ID, useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import { FireMap } from './controller'

const emit = defineEmits<{ ready: [] }>()
const query = useQueryStore()
const ui = useUiStore()
const live = useLiveStore()

const container = ref<HTMLElement | null>(null)
const fireMap = shallowRef<FireMap | null>(null)
const compareScene = shallowRef<SceneSummary | null>(null)
const EMPTY = { type: 'FeatureCollection' as const, features: [] }
// Длинный контур в адрес тайла не влезет: такой полигон оставляем без ограничения выдачи.
const CLIP_MAX_POINTS = 400

/** Ключ выбранной области для тайлов гарей: id региона, свой контур или пусто на всей территории. */
function clipKey(): string {
  const geometry = query.geometry
  if (query.regionId === AOI_REGION_ID || !geometry) return ''
  if (query.regionId) return query.regionId
  const rings = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  const ring = rings[0][0]
  if (rings.length > 1 || ring.length > CLIP_MAX_POINTS) return ''
  return `p:${ring.map(([lon, lat]) => `${lon.toFixed(5)},${lat.toFixed(5)}`).join(';')}`
}

defineExpose({
  flyTo: (lon: number, lat: number, zoom?: number) => fireMap.value?.flyTo(lon, lat, zoom),
  setSceneQuicklook: (name: string) => fireMap.value?.showScene(compareScene.value, name),
})

function syncTime() {
  fireMap.value?.setTimeWindow({
    fromDay: dayNumber(query.dateFrom),
    toDay: dayNumber(query.dateTo),
    playheadTs: ui.playhead,
  })
}

function themeBackground(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--background').trim() || '#120f0d'
}

onMounted(async () => {
  const instance = await FireMap.create(container.value!, ui.theme, themeBackground(), {
    onSceneClick: (sceneId) => (ui.passportTarget = { type: 'scene', id: sceneId }),
    onHotspotClick: (id) => (ui.passportTarget = { type: 'hotspot', id }),
    onDrawn: (geometry) => {
      ui.drawMode = 'idle'
      query.setCustomGeometry(geometry)
    },
  })
  fireMap.value = instance
  if (import.meta.env.DEV) (window as unknown as { __fireMap: FireMap }).__fireMap = instance
  emit('ready')

  watch(() => query.meta, (meta) => meta && instance.setStatic(meta.aoi, meta.regions), { immediate: true })
  watch(() => query.geometry, (geometry) => geometry && instance.setFocus(geometry), { immediate: true })
  watch(() => query.result, (result) => instance.setHotspots(result?.hotspots ?? (EMPTY as never)), { immediate: true })
  watch([() => query.dateFrom, () => query.dateTo, () => ui.playhead], syncTime, { immediate: true })
  watch([() => ui.showFiltered, () => ui.showSeverity], ([filtered, severity]) => instance.setLayerToggles(filtered, severity), { immediate: true })
  watch(() => ui.filters, (filters) => instance.setDisplayFilters(filters), { immediate: true, deep: true })
  watch(() => ui.basemap, (basemap) => instance.setBasemap(basemap), { immediate: true })
  watch(() => ui.theme, (theme) => void instance.setTheme(theme, themeBackground()), { flush: 'post' })
  watch(() => live.zones, (zones) => instance.setZones(zones), { immediate: true })
  watch(() => query.meta?.tiles_version, (version) => version != null && instance.refreshTiles(version), { immediate: true })
  watch([() => query.regionId, () => query.geometry], () => instance.setClip(clipKey()), { immediate: true })
  watch(
    [() => ui.showSources, () => live.dataVersion],
    async ([visible]) => instance.setSources(visible ? await api.sources() : EMPTY, visible),
    { immediate: true },
  )
  watch(() => ui.flyTarget, (target) => target && instance.flyTo(target.lon, target.lat, target.zoom))
  watch(() => ui.drawMode, (mode) => (mode === 'idle' ? instance.stopDraw() : void instance.startDraw(mode)))
  watch(() => ui.passport, (event) => instance.showEvent(event), { immediate: true })
  watch(
    () => ui.compareSceneId,
    async (sceneId) => {
      compareScene.value = sceneId ? await api.scene(sceneId) : null
      instance.showScene(compareScene.value, compareScene.value?.kind === 'bs' ? 'rgb_post' : 'thermal')
      if (!sceneId && ui.passport) instance.showEvent(ui.passport)
      else if (!sceneId && query.geometry) instance.setFocus(query.geometry)
    },
  )
})

onBeforeUnmount(() => fireMap.value?.destroy())
</script>

<template>
  <div class="absolute inset-0" :class="{ 'cursor-crosshair': ui.drawMode !== 'idle' }">
    <div ref="container" class="size-full" />
  </div>
</template>
