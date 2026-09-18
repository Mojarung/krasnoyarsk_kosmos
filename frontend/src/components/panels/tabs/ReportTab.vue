<script setup lang="ts">
import { Crosshair, Download, Flame, Info, ShieldCheck, Siren, Target } from '@lucide/vue'
import { ref } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import MetricTile from '@/components/common/MetricTile.vue'
import SeverityBar from '@/components/common/SeverityBar.vue'
import { Button } from '@/components/ui/button'
import { download } from '@/lib/api'
import { fmt } from '@/lib/format'
import type { Report } from '@/lib/types'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ report: Report }>()
const query = useQueryStore()
const ui = useUiStore()

type Layer = 'contours' | 'severity'
const layer = ref<Layer>('contours')
const busy = ref<string | null>(null)
const failure = ref<string | null>(null)

const LAYERS = [
  { value: 'contours' as const, label: 'Контуры' },
  { value: 'severity' as const, label: 'Степени' },
]
const VECTOR = [
  { format: 'geojson', label: 'GeoJSON' },
  { format: 'shp', label: 'Shapefile' },
  { format: 'gpkg', label: 'GeoPackage' },
  { format: 'kml', label: 'KML' },
]
const REPORT = ['json', 'csv', 'xlsx', 'pdf']

async function save(path: string, key: string) {
  if (!query.params) return
  busy.value = key
  failure.value = null
  try {
    await download(path, query.params, key)
  } catch (e) {
    failure.value = e instanceof Error ? e.message : 'Не удалось выгрузить'
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="space-y-3">
    <div class="relative overflow-hidden rounded-[24px] bg-primary-container px-5 py-3.5 text-on-primary-container">
      <div class="label-caps !text-current opacity-70">Пройдено огнём</div>
      <div class="mt-1 flex items-baseline gap-2">
        <AnimatedNumber :value="props.report.burn.total_ha" :format="fmt.ha" class="display-number text-[40px]" />
        <span class="text-lg opacity-80">га</span>
      </div>
      <div class="mt-1.5 text-xs opacity-75">
        {{ fmt.int(props.report.burn.contours) }} контуров · {{ props.report.burn.scenes }} сцен ·
        {{ fmt.pct(props.report.burn.burned_share) }} территории запроса
      </div>
    </div>

    <SeverityBar :items="props.report.burn.by_severity" />

    <div class="grid grid-cols-2 gap-2">
      <MetricTile label="Природных очагов" :value="fmt.int(props.report.hotspots.fire_clusters)" :icon="Flame" tone="fire" :hint="props.report.method.hotspots" />
      <MetricTile label="Термоточек пожаров" :value="fmt.int(props.report.hotspots.fire)" :icon="Target" />
      <MetricTile label="Отфильтровано срабатываний" :value="fmt.int(props.report.hotspots.technogenic + props.report.hotspots.glint)" :icon="ShieldCheck" tone="technogenic" />
      <MetricTile label="Ложных выездов предотвращено" :value="fmt.int(props.report.hotspots.false_dispatches_prevented)" :icon="Siren" tone="tertiary" />
    </div>

    <div v-if="props.report.burn.largest.length">
      <div class="label-caps mb-1.5">Крупнейшие гари</div>
      <div class="space-y-1">
        <button
          v-for="item in props.report.burn.largest.slice(0, 2)"
          :key="item.contour_id"
          type="button"
          class="flex w-full items-center justify-between rounded-full bg-surface-2 px-3.5 py-2 text-[13px] transition-[border-radius,background-color] duration-300 ease-spring hover:rounded-2xl hover:bg-surface-3"
          @click="ui.flyTarget = { lon: item.lon, lat: item.lat, zoom: 11 }"
        >
          <span class="flex items-center gap-2"><Crosshair class="size-3.5 text-primary" />{{ fmt.date(item.date_post) }}</span>
          <span class="font-medium tabular-nums">{{ fmt.ha(item.area_ha) }} га</span>
        </button>
      </div>
    </div>

    <div class="rounded-[22px] bg-surface-2 p-3.5">
      <div class="mb-2.5 flex items-center justify-between">
        <span class="flex items-center gap-1.5 text-[13px] font-medium" :title="props.report.method.area"><Download class="size-3.5" />Выгрузка<Info class="size-3 text-muted-foreground" /></span>
        <BubbleTabs v-model="layer" :options="LAYERS" size="sm" />
      </div>
      <div class="flex flex-wrap gap-1.5">
        <Button v-for="item in VECTOR" :key="item.format" size="xs" variant="tonal" :disabled="busy !== null" @click="save(`/api/v1/burns?layer=${layer}&format=${item.format}`, `burn_${layer}.${item.format}`)">
          {{ busy === `burn_${layer}.${item.format}` ? '...' : item.label }}
        </Button>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-1.5">
        <span class="mr-1 text-xs text-muted-foreground">Справка</span>
        <Button v-for="format in REPORT" :key="format" size="xs" variant="outline" class="uppercase" :disabled="busy !== null" @click="save(`/api/v1/report?format=${format}`, `report.${format}`)">
          {{ busy === `report.${format}` ? '...' : format }}
        </Button>
      </div>
      <p v-if="failure" class="mt-2 text-xs text-destructive">{{ failure }}</p>
      <p class="mt-2 text-[11px] leading-snug text-muted-foreground">Площади считаются в UTM зоны сцены, {{ props.report.burn.by_severity.length }} степени, атрибуты: id контура, степень, га.</p>
    </div>
  </div>
</template>
