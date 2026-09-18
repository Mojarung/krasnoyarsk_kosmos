<script setup lang="ts">
import { CalendarRange, ChevronLeft, Layers, Map as MapIcon, MapPinned, PenTool, Satellite, SlidersHorizontal, Square, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import FoldSection from '@/components/common/FoldSection.vue'
import MorphPanel from '@/components/common/MorphPanel.vue'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { fmt } from '@/lib/format'
import { AOI_REGION_ID, useQueryStore } from '@/stores/query'
import { type Basemap, useUiStore } from '@/stores/ui'

type Section = 'area' | 'period' | 'layers'

const query = useQueryStore()
const ui = useUiStore()

const FIRE_SEASON = { from: '-04-01', to: '-10-31' }
const BASEMAPS: { value: Basemap; label: string; icon: typeof MapIcon; hint: string }[] = [
  { value: 'dark', label: 'Схема', icon: MapIcon, hint: 'Векторная карта OpenFreeMap с русскими подписями' },
  { value: 'satellite', label: 'Спутник', icon: Satellite, hint: 'Снимки Esri World Imagery под подписями' },
]

const opened = ref<Section | null>('area')

const regions = computed(() => [
  { id: AOI_REGION_ID, name: 'Вся территория' },
  ...(query.meta?.regions.features.map((f) => ({ id: f.properties.id, name: f.properties.name.replace(' область', ' обл.').replace('Республика ', '') })) ?? []),
])
const years = computed(() => {
  const data = query.meta?.data
  if (!data?.date_min || !data.date_max) return []
  const first = Number(data.date_min.slice(0, 4))
  return Array.from({ length: Number(data.date_max.slice(0, 4)) - first + 1 }, (_, i) => first + i)
})
const activeYear = computed(() => {
  const year = query.dateFrom.slice(0, 4)
  return query.dateFrom === year + FIRE_SEASON.from && query.dateTo === year + FIRE_SEASON.to ? Number(year) : null
})
const isFullRange = computed(() => query.dateFrom === query.meta?.data.date_min && query.dateTo === query.meta?.data.date_max)
const periodSummary = computed(() => (activeYear.value ? `сезон ${activeYear.value}` : isFullRange.value ? 'весь охват' : `${fmt.date(query.dateFrom)} - ${fmt.date(query.dateTo)}`))
const layersSummary = computed(() =>
  [ui.basemap === 'satellite' ? 'спутник' : 'схема', ui.showSeverity && 'гари', ui.showFiltered && 'отсеянные', ui.showSources && 'источники'].filter(Boolean).join(', '),
)

function toggle(section: Section) {
  opened.value = opened.value === section ? null : section
}

function pickYear(year: number) {
  query.setPeriod(year + FIRE_SEASON.from, year + FIRE_SEASON.to)
}

function fullRange() {
  const data = query.meta?.data
  if (data?.date_min && data.date_max) query.setPeriod(data.date_min, data.date_max)
}

function toggleDraw(mode: 'polygon' | 'rectangle') {
  ui.drawMode = ui.drawMode === mode ? 'idle' : mode
}
</script>

<template>
  <MorphPanel :open="ui.queryOpen" class="flex max-h-full w-[330px] flex-col" pill-class="w-fit">
    <template #pill>
      <button v-tip="'Развернуть панель запроса'" type="button" class="flex h-12 items-center gap-2.5 pl-4 pr-5 text-sm font-medium" @click="ui.queryOpen = true">
        <SlidersHorizontal class="size-4 text-primary" />
        <span class="max-w-44 truncate">{{ query.regionName }}</span>
      </button>
    </template>

    <header class="flex items-center justify-between pl-5 pr-3 pt-3">
      <span class="label-caps">Запрос</span>
      <Button v-tip="'Свернуть панель, карта станет шире'" variant="ghost" size="icon-sm" aria-label="Свернуть панель запроса" @click="ui.queryOpen = false"><ChevronLeft /></Button>
    </header>

    <div class="thin-scroll flex-1 space-y-1 overflow-y-auto p-2">
      <FoldSection title="Территория" :summary="query.regionName" :icon="MapPinned" :open="opened === 'area'" @toggle="toggle('area')">
        <div class="flex flex-wrap gap-1.5">
          <Button v-for="region in regions" :key="region.id" size="sm" :variant="query.regionId === region.id ? 'tonal' : 'outline'" @click="query.selectRegion(region.id)">
            {{ region.name }}
          </Button>
        </div>
        <div class="mt-3 flex gap-1.5">
          <Button v-tip="'Нарисовать свою территорию: вершины кликами, замкнуть на первой точке'" size="sm" :variant="ui.drawMode === 'polygon' ? 'default' : 'secondary'" class="flex-1" @click="toggleDraw('polygon')">
            <component :is="ui.drawMode === 'polygon' ? X : PenTool" />{{ ui.drawMode === 'polygon' ? 'Отмена' : 'Полигон' }}
          </Button>
          <Button v-tip="'Задать прямоугольник двумя кликами по противоположным углам'" size="sm" :variant="ui.drawMode === 'rectangle' ? 'default' : 'secondary'" class="flex-1" @click="toggleDraw('rectangle')">
            <component :is="ui.drawMode === 'rectangle' ? X : Square" />{{ ui.drawMode === 'rectangle' ? 'Отмена' : 'Прямоугольник' }}
          </Button>
        </div>
        <p v-if="ui.drawMode !== 'idle'" class="mt-2 text-xs text-primary">
          {{ ui.drawMode === 'polygon' ? 'Ставьте вершины кликами, замкните контур на первой точке' : 'Кликните два противоположных угла' }}
        </p>
      </FoldSection>

      <FoldSection title="Период" :summary="periodSummary" :icon="CalendarRange" :open="opened === 'period'" @toggle="toggle('period')">
        <div class="grid grid-cols-2 gap-2">
          <label class="rounded-2xl bg-surface-3 px-3 py-2 text-[11px] text-muted-foreground">
            с
            <input type="date" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none" :value="query.dateFrom" :max="query.dateTo" @change="query.setPeriod(($event.target as HTMLInputElement).value, query.dateTo)" />
          </label>
          <label class="rounded-2xl bg-surface-3 px-3 py-2 text-[11px] text-muted-foreground">
            по
            <input type="date" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none" :value="query.dateTo" :min="query.dateFrom" @change="query.setPeriod(query.dateFrom, ($event.target as HTMLInputElement).value)" />
          </label>
        </div>
        <div class="mt-2.5 flex flex-wrap gap-1.5">
          <Button v-tip="'Все даты, за которые загружены сцены'" size="xs" :variant="isFullRange ? 'tonal' : 'outline'" @click="fullRange">Весь охват</Button>
          <Button v-for="year in years" :key="year" v-tip="`Пожароопасный сезон ${year}: апрель - октябрь`" size="xs" :variant="activeYear === year ? 'tonal' : 'outline'" @click="pickYear(year)">{{ year }}</Button>
        </div>
      </FoldSection>

      <FoldSection title="Слои" :summary="layersSummary" :icon="Layers" :open="opened === 'layers'" @toggle="toggle('layers')">
        <div class="space-y-3 text-[13px]">
          <label v-tip="'Контуры гарей и полигоны трёх степеней поражения'" class="flex items-center justify-between gap-3">Гари и степени<Switch v-model="ui.showSeverity" /></label>
          <label v-tip="'Техногенные источники и блики, которые модель отсеяла. Кольца на карте, причина в подсказке точки'" class="flex items-center justify-between gap-3">Отсеянные срабатывания<Switch v-model="ui.showFiltered" /></label>
          <label v-tip="'Факелы и печи, найденные по истории: горят почти в каждом пролёте из года в год'" class="flex items-center justify-between gap-3">Постоянные источники<Switch v-model="ui.showSources" /></label>
        </div>
        <BubbleTabs v-model="ui.basemap" :options="BASEMAPS" size="sm" stretch class="mt-3.5" />
      </FoldSection>
    </div>
  </MorphPanel>
</template>
