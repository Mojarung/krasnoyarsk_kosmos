<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { api } from '@/lib/api'
import { dayNumber } from '@/lib/format'
import type { SceneSummary } from '@/lib/types'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'
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

onMounted(async () => {
  const background = getComputedStyle(document.documentElement).getPropertyValue('--background').trim() || '#120f0d'
  const instance = new FireMap(container.value!, background, {
    onSceneClick: (sceneId) => (ui.compareSceneId = sceneId),
    onDrawn: (geometry) => {
      ui.drawMode = 'idle'
      query.setCustomGeometry(geometry)
    },
  })
  await instance.ready
  fireMap.value = instance
  emit('ready')

  watch(() => query.meta, (meta) => meta && instance.setStatic(meta.aoi, meta.regions), { immediate: true })
  watch(() => query.geometry, (geometry) => geometry && instance.setFocus(geometry), { immediate: true })
  watch(() => query.result, (result) => instance.setHotspots(result?.hotspots ?? (EMPTY as never)), { immediate: true })
  watch([() => query.dateFrom, () => query.dateTo, () => ui.playhead], syncTime, { immediate: true })
  watch([() => ui.showFiltered, () => ui.showSeverity], ([filtered, severity]) => instance.setLayerToggles(filtered, severity), { immediate: true })
  watch(() => ui.basemap, (basemap) => instance.setBasemap(basemap), { immediate: true })
  watch(() => live.zones, (zones) => instance.setZones(zones), { immediate: true })
  watch(() => live.dataVersion, (version) => instance.refreshTiles(version))
  watch(
    [() => ui.showSources, () => live.dataVersion],
    async ([visible]) => instance.setSources(visible ? await api.sources() : EMPTY, visible),
    { immediate: true },
  )
  watch(() => ui.flyTarget, (target) => target && instance.flyTo(target.lon, target.lat, target.zoom))
  watch(() => ui.drawMode, (mode) => (mode === 'idle' ? instance.stopDraw() : void instance.startDraw(mode)))
  watch(
    () => ui.compareSceneId,
    async (sceneId) => {
      compareScene.value = sceneId ? await api.scene(sceneId) : null
      instance.showScene(compareScene.value, compareScene.value?.kind === 'bs' ? 'rgb_post' : 'thermal')
      if (!sceneId && query.geometry) instance.setFocus(query.geometry)
    },
  )
})

onBeforeUnmount(() => fireMap.value?.destroy())
</script>

<template>
  <div ref="container" class="absolute inset-0" :class="{ 'cursor-crosshair': ui.drawMode !== 'idle' }" />
</template>
