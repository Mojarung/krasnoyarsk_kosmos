<script setup lang="ts">
import { Factory, Sun } from '@lucide/vue'
import type { Feature, Point } from 'geojson'
import { computed, onMounted, shallowRef, watch } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { fmt } from '@/lib/format'
import type { Report } from '@/lib/types'
import { useLiveStore } from '@/stores/live'
import { useUiStore } from '@/stores/ui'

interface SourceProps {
  n_days: number
  n_passes: number
  n_years: number
  n_detections: number
}

const props = defineProps<{ report: Report }>()
const ui = useUiStore()
const live = useLiveStore()
const sources = shallowRef<Feature<Point, SourceProps>[]>([])

const hot = computed(() => props.report.hotspots)
const segments = computed(() => [
  { key: 'fire', label: 'Природные пожары', value: hot.value.fire, color: 'var(--fire)' },
  { key: 'technogenic', label: 'Техногенные источники', value: hot.value.technogenic, color: 'var(--technogenic)' },
  { key: 'glint', label: 'Блики', value: hot.value.glint, color: 'var(--glint)' },
])

async function load() {
  sources.value = (await api.sources()).features as Feature<Point, SourceProps>[]
}

onMounted(load)
watch(() => live.dataVersion, load)
</script>

<template>
  <div class="space-y-3.5">
    <div class="rounded-[24px] bg-technogenic/15 px-5 py-4">
      <div class="label-caps">Ложных выездов предотвращено</div>
      <div class="mt-1 flex items-baseline gap-2">
        <AnimatedNumber :value="hot.false_dispatches_prevented" class="display-number text-[44px]" />
        <span class="text-sm text-muted-foreground">из {{ fmt.int(hot.raw_total) }} термоаномалий отсеяно {{ fmt.pct(hot.filtered_share) }}</span>
      </div>
    </div>

    <div>
      <div class="flex h-3 gap-0.5 overflow-hidden rounded-full bg-surface-3">
        <div v-for="s in segments" :key="s.key" class="h-full rounded-full transition-[flex-grow] duration-700 ease-spring" :style="{ flexGrow: s.value || 0.001, flexBasis: 0, background: s.color }" />
      </div>
      <div class="mt-2 space-y-1">
        <div v-for="s in segments" :key="s.key" class="flex items-center justify-between text-[13px]">
          <span class="flex items-center gap-2"><span class="size-2 rounded-full" :style="{ background: s.color }" />{{ s.label }}</span>
          <span class="font-medium tabular-nums">{{ fmt.int(s.value) }}</span>
        </div>
      </div>
    </div>

    <label class="flex items-center justify-between gap-3 rounded-full bg-surface-2 px-4 py-2.5 text-[13px]">
      Показывать отсеянные на карте<Switch v-model="ui.showFiltered" />
    </label>

    <div>
      <div class="mb-1.5 flex items-center justify-between">
        <span class="label-caps">Постоянные источники: {{ sources.length }}</span>
        <label class="flex items-center gap-2 text-xs text-muted-foreground">на карте<Switch v-model="ui.showSources" /></label>
      </div>
      <div class="thin-scroll max-h-40 space-y-1 overflow-y-auto pr-1">
        <button
          v-for="(source, index) in sources.slice(0, 40)"
          :key="index"
          type="button"
          class="flex w-full items-center justify-between rounded-full bg-surface-2 px-3.5 py-1.5 text-xs transition-[border-radius,background-color] duration-300 ease-spring hover:rounded-xl hover:bg-surface-3"
          @click="ui.flyTarget = { lon: source.geometry.coordinates[0], lat: source.geometry.coordinates[1], zoom: 12 }"
        >
          <span class="flex items-center gap-2"><Factory class="size-3.5 text-technogenic" />{{ source.geometry.coordinates[1].toFixed(3) }}, {{ source.geometry.coordinates[0].toFixed(3) }}</span>
          <span class="tabular-nums text-muted-foreground">{{ source.properties.n_days }} из {{ source.properties.n_passes }} пролётов · {{ source.properties.n_years }} г.</span>
        </button>
        <p v-if="!sources.length" class="px-1 text-xs text-muted-foreground">Пока не найдены. Правило: 5+ дней, 3+ года, горит в 40%+ пролётов.</p>
      </div>
    </div>

    <p class="flex gap-2 text-[11px] leading-snug text-muted-foreground">
      <Sun class="mt-0.5 size-3.5 shrink-0" />
      Факел по одному снимку неотличим от пожара. Его выдаёт история: одна и та же ячейка горит из пролёта в пролёт и из года в год.
    </p>
  </div>
</template>
