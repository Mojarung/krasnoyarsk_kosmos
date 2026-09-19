<script setup lang="ts">
import { Factory } from '@lucide/vue'
import type { Feature, Point } from 'geojson'
import { computed, onMounted, shallowRef, watch } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { fmt, plural } from '@/lib/format'
import { TERMS } from '@/lib/glossary'
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
  { key: 'fire', label: 'Природные пожары', value: hot.value.fire, color: 'var(--fire)', hint: TERMS.naturalFire },
  { key: 'technogenic', label: 'Техногенные источники', value: hot.value.technogenic, color: 'var(--technogenic)', hint: TERMS.technogenic },
  { key: 'glint', label: 'Блики', value: hot.value.glint, color: 'var(--glint)', hint: TERMS.glint },
])

async function load() {
  sources.value = (await api.sources()).features as Feature<Point, SourceProps>[]
}

onMounted(load)
watch(() => live.dataVersion, load)
</script>

<template>
  <div class="grid items-start gap-4 @2xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] @4xl:grid-cols-[minmax(0,0.75fr)_minmax(0,1.6fr)]">
    <div class="space-y-3.5">
    <div class="rounded-[24px] bg-technogenic/15 px-5 py-4">
      <div class="label-caps">Выездов сэкономлено</div>
      <div class="mt-1 flex items-baseline gap-2">
        <AnimatedNumber :value="hot.false_dispatches_prevented" class="display-number text-[44px]" />
        <span class="text-sm text-muted-foreground">из {{ fmt.int(hot.raw_total) }} термоточек отсеяно {{ fmt.pct(hot.filtered_share) }}</span>
      </div>
    </div>

    <div>
      <div class="flex h-3 gap-0.5 overflow-hidden rounded-full bg-surface-3">
        <div v-for="s in segments" :key="s.key" class="h-full rounded-full transition-[flex-grow] duration-700 ease-spring" :style="{ flexGrow: s.value || 0.001, flexBasis: 0, background: s.color }" />
      </div>
      <div class="mt-2 space-y-1">
        <div v-for="s in segments" :key="s.key" v-tip="s.hint" class="flex items-center justify-between text-[13px]">
          <span class="flex items-center gap-2"><span class="size-2 rounded-full" :style="{ background: s.color }" /><span class="term">{{ s.label }}</span></span>
          <span class="font-medium tabular-nums">{{ fmt.int(s.value) }}</span>
        </div>
      </div>
    </div>

    <label class="flex items-center justify-between gap-3 rounded-full bg-surface-2 px-4 py-2.5 text-[13px]">
      Показывать отсеянные на карте<Switch v-model="ui.showFiltered" />
    </label>
</div>

    <div>
      <div class="mb-1.5 flex items-center justify-between">
        <span v-tip="TERMS.persistentSource" class="label-caps"><span class="term">Постоянные источники</span>: {{ sources.length }}</span>
        <label class="flex items-center gap-2 text-xs text-muted-foreground">на карте<Switch v-model="ui.showSources" /></label>
      </div>
      <div class="thin-scroll grid max-h-40 gap-1 overflow-y-auto pr-1 @2xl:max-h-[min(520px,52vh)] @4xl:grid-cols-2">
        <button
          v-for="(source, index) in sources.slice(0, 40)"
          :key="index"
          v-tip="'Показать на карте. Панель свернётся до сводки'"
          type="button"
          class="flex w-full items-center justify-between gap-2 rounded-full bg-surface-2 px-3.5 py-1.5 text-xs transition-colors duration-200 hover:bg-surface-3 active:scale-[0.99]"
          @click="ui.flyTarget = { lon: source.geometry.coordinates[0], lat: source.geometry.coordinates[1], zoom: 12 }"
        >
          <span class="flex items-center gap-2 whitespace-nowrap"><Factory class="size-3.5 shrink-0 text-technogenic" />{{ source.geometry.coordinates[1].toFixed(3) }}, {{ source.geometry.coordinates[0].toFixed(3) }}</span>
          <span class="truncate tabular-nums text-muted-foreground">{{ source.properties.n_days }} из {{ source.properties.n_passes }} пролётов, {{ plural(source.properties.n_years, ['год', 'года', 'лет']) }}</span>
        </button>
        <p v-if="!sources.length" class="px-1 text-xs text-muted-foreground">Пока не найдены. Источник считается постоянным, если горел не меньше 5 дней, в 3 разных годах и хотя бы в 40 % пролётов.</p>
      </div>
    </div>
  </div>
</template>
