<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { LngLatBounds, Map as MapLibre, Marker, setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { Inspection } from '@/lib/inspections'
import { loadBaseStyle } from './style'

const props = defineProps<{ task: Inspection }>()
const container = ref<HTMLElement | null>(null)
const error = ref(false)
let map: MapLibre | null = null
let disposed = false
onMounted(async () => {
  try {
    setWorkerUrl(workerUrl)
    const style = await loadBaseStyle(document.documentElement.classList.contains('dark') ? 'dark' : 'light', '#171513')
    if (disposed || !container.value) return
    map = new MapLibre({ container: container.value, style, center: props.task.site, zoom: 13, attributionControl: { compact: true } })
    const bounds = new LngLatBounds(props.task.site, props.task.site)
    for (const [point, number] of [[props.task.site, '1'], [props.task.access, '2']] as const) {
      if (!point) continue
      const element = document.createElement('div')
      element.className = 'inspection-marker'; element.textContent = number
      new Marker({ element }).setLngLat(point).addTo(map)
      bounds.extend(point)
    }
    map.fitBounds(bounds, { padding: 50, maxZoom: 14, duration: 0 })
    map.on('error', () => { error.value = true })
  } catch { error.value = true }
})
onBeforeUnmount(() => { disposed = true; map?.remove() })
</script>

<template>
  <div class="relative overflow-hidden rounded-[20px] border">
    <div ref="container" class="h-56 w-full" aria-label="Карта места осмотра и остановки" />
    <p v-if="error" class="absolute inset-x-2 top-2 rounded-lg bg-surface-1 p-2 text-xs" role="status">Подложка карты недоступна. Координаты и ссылки ниже доступны.</p>
  </div>
</template>
