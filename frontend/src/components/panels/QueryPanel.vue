<script setup lang="ts">
import { CalendarRange, ChevronLeft, Funnel, Layers, Map as MapIcon, MapPinned, PenTool, Satellite, SlidersHorizontal, Square, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import DateField from '@/components/common/DateField.vue'
import FoldSection from '@/components/common/FoldSection.vue'
import MorphPanel from '@/components/common/MorphPanel.vue'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { fmt } from '@/lib/format'
import { AOI_REGION_ID, useQueryStore } from '@/stores/query'
import { type Basemap, type DayNight, useUiStore } from '@/stores/ui'

type Section = 'area' | 'period' | 'layers' | 'filters'

const query = useQueryStore()
const ui = useUiStore()

const FIRE_SEASON = { from: '-04-01', to: '-10-31' }
const BASEMAPS: { value: Basemap; label: string; icon: typeof MapIcon; hint: string }[] = [
  { value: 'dark', label: 'Схема', icon: MapIcon, hint: 'Векторная карта OpenFreeMap с русскими подписями' },
  { value: 'satellite', label: 'Спутник', icon: Satellite, hint: 'Снимки Esri World Imagery под подписями' },
]

const SEVERITIES = [
  { value: 1, label: 'Слабая', color: 'var(--sev-1)' },
  { value: 2, label: 'Средняя', color: 'var(--sev-2)' },
  { value: 3, label: 'Сильная', color: 'var(--sev-3)' },
]
const AREA_STEPS = [0, 10, 50, 100, 500, 1000]
const CONFIDENCE_STEPS = [0, 0.5, 0.7, 0.9]
const SATELLITES = [
  { value: 'SNPP', label: 'Suomi NPP' },
  { value: 'NOAA20', label: 'NOAA-20' },
  { value: 'NOAA21', label: 'NOAA-21' },
]
const DAY_NIGHT: { value: DayNight; label: string; hint: string }[] = [
  { value: 'all', label: 'Все', hint: 'Дневные и ночные пролёты' },
  { value: 'day', label: 'День', hint: 'Только дневные пролёты' },
  { value: 'night', label: 'Ночь', hint: 'Только ночные пролёты: сигнал слабее, но нет бликов' },
]

const opened = ref<Section | null>('area')
const filtersSummary = computed(() => (ui.activeFilterCount ? `активно: ${ui.activeFilterCount}` : 'показано всё'))

function toggleIn<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value]
}

function setArea(raw: string) {
  const value = Number(raw)
  ui.filters.minContourHa = Number.isFinite(value) && value > 0 ? Math.round(value) : 0
}

function setConfidence(raw: string) {
  const value = Number(raw)
  ui.filters.minConfidence = Number.isFinite(value) ? Math.min(Math.max(value, 0), 1) : 0
}

function toggleSeverity(value: number) {
  const next = toggleIn(ui.filters.severities, value)
  if (next.length) ui.filters.severities = next.sort()
}

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

    <div class="thin-scroll min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
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
          <DateField label="с" :model-value="query.dateFrom" :max="query.dateTo" hint="Начало периода. Откроется календарь" @update:model-value="(value: string) => query.setPeriod(value, query.dateTo)" />
          <DateField label="по" :model-value="query.dateTo" :min="query.dateFrom" hint="Конец периода. Откроется календарь" @update:model-value="(value: string) => query.setPeriod(query.dateFrom, value)" />
        </div>
        <div class="mt-2.5 flex flex-wrap gap-1.5">
          <Button v-tip="'Все даты, за которые загружены сцены'" size="xs" :variant="isFullRange ? 'tonal' : 'outline'" @click="fullRange">Весь охват</Button>
          <Button v-for="year in years" :key="year" v-tip="`Пожароопасный сезон ${year}: апрель - октябрь`" size="xs" :variant="activeYear === year ? 'tonal' : 'outline'" @click="pickYear(year)">{{ year }}</Button>
        </div>
      </FoldSection>

      <FoldSection title="Слои" :summary="layersSummary" :icon="Layers" :open="opened === 'layers'" @toggle="toggle('layers')">
        <div class="space-y-3 text-[13px]">
          <label v-tip="'Контуры гарей и полигоны трёх степеней поражения'" class="flex items-center justify-between gap-3">Гари и степени<Switch v-model="ui.showSeverity" /></label>
          <label v-tip="'Техногенные источники и блики, которые модель отсеяла. На карте это кольца, причина видна при наведении'" class="flex items-center justify-between gap-3">Отсеянные срабатывания<Switch v-model="ui.showFiltered" /></label>
          <label v-tip="'Факелы и печи, найденные по истории: горят почти в каждом пролёте из года в год'" class="flex items-center justify-between gap-3">Постоянные источники<Switch v-model="ui.showSources" /></label>
        </div>
        <BubbleTabs v-model="ui.basemap" :options="BASEMAPS" size="sm" stretch class="mt-3.5" />
      </FoldSection>

      <FoldSection title="Фильтры карты" :summary="filtersSummary" :icon="Funnel" :open="opened === 'filters'" @toggle="toggle('filters')">
        <div class="space-y-3.5 text-[13px]">
          <div>
            <div class="mb-1.5 text-xs text-muted-foreground">Степень поражения</div>
            <div class="flex gap-1.5">
              <Button v-for="item in SEVERITIES" :key="item.value" v-tip="`Показывать гари со степенью: ${item.label.toLowerCase()}`" size="xs" :variant="ui.filters.severities.includes(item.value) ? 'tonal' : 'outline'" class="flex-1" @click="toggleSeverity(item.value)">
                <i class="size-2 rounded-full" :style="{ background: item.color }" />{{ item.label }}
              </Button>
            </div>
          </div>
          <div>
            <div class="mb-1.5 text-xs text-muted-foreground">Площадь контура не меньше, га</div>
            <div class="flex flex-wrap gap-1.5">
              <Button v-for="step in AREA_STEPS" :key="step" v-tip="step ? `Скрыть гари меньше ${step} га` : 'Показывать все гари'" size="xs" :variant="ui.filters.minContourHa === step ? 'tonal' : 'outline'" @click="ui.filters.minContourHa = step">{{ step || 'все' }}</Button>
              <input
                v-tip="'Своё значение в гектарах'"
                type="number"
                min="0"
                step="1"
                inputmode="numeric"
                placeholder="своё"
                aria-label="Минимальная площадь контура, га"
                class="h-7 w-20 rounded-full bg-surface-3 px-3 text-xs tabular-nums outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/50"
                :class="!AREA_STEPS.includes(ui.filters.minContourHa) && 'ring-2 ring-primary/60'"
                :value="AREA_STEPS.includes(ui.filters.minContourHa) ? '' : ui.filters.minContourHa"
                @change="setArea(($event.target as HTMLInputElement).value)"
              />
            </div>
          </div>
          <div>
            <div class="mb-1.5 text-xs text-muted-foreground">Термоточки: время пролёта</div>
            <BubbleTabs v-model="ui.filters.dayNight" :options="DAY_NIGHT" size="sm" stretch />
          </div>
          <div>
            <div class="mb-1.5 text-xs text-muted-foreground">Уверенность модели не ниже</div>
            <div class="flex gap-1.5">
              <Button v-for="step in CONFIDENCE_STEPS" :key="step" v-tip="step ? `Только термоточки с вероятностью горения от ${step}` : 'Все термоточки выше порога модели'" size="xs" :variant="ui.filters.minConfidence === step ? 'tonal' : 'outline'" class="flex-1" @click="ui.filters.minConfidence = step">{{ step ? step.toFixed(1) : 'любая' }}</Button>
              <input
                v-tip="'Своё значение от 0 до 1'"
                type="number"
                min="0"
                max="1"
                step="0.05"
                inputmode="decimal"
                placeholder="своё"
                aria-label="Минимальная уверенность модели"
                class="h-7 w-20 shrink-0 rounded-full bg-surface-3 px-3 text-xs tabular-nums outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/50"
                :class="!CONFIDENCE_STEPS.includes(ui.filters.minConfidence) && 'ring-2 ring-primary/60'"
                :value="CONFIDENCE_STEPS.includes(ui.filters.minConfidence) ? '' : ui.filters.minConfidence"
                @change="setConfidence(($event.target as HTMLInputElement).value)"
              />
            </div>
          </div>
          <div>
            <div class="mb-1.5 text-xs text-muted-foreground">Спутник</div>
            <div class="flex gap-1.5">
              <Button v-for="item in SATELLITES" :key="item.value" v-tip="'Ни один не выбран: показаны все спутники'" size="xs" :variant="ui.filters.satellites.includes(item.value) ? 'tonal' : 'outline'" class="flex-1" @click="ui.filters.satellites = toggleIn(ui.filters.satellites, item.value)">{{ item.label }}</Button>
            </div>
          </div>
          <div class="flex items-center justify-between gap-3 border-t border-border/60 pt-3">
            <span class="text-[11px] leading-snug text-muted-foreground">Фильтры меняют только карту. Справка считается по всему запросу.</span>
            <Button v-tip="'Вернуть все фильтры в исходное состояние'" size="xs" variant="ghost" :disabled="!ui.activeFilterCount" @click="ui.resetFilters()">Сбросить</Button>
          </div>
        </div>
      </FoldSection>
    </div>
  </MorphPanel>
</template>
