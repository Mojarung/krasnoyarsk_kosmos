<script setup lang="ts">
import { BellPlus, ChevronLeft, Layers, Map as MapIcon, PenTool, Satellite, SlidersHorizontal, Square, X } from '@lucide/vue'
import { useClipboard } from '@vueuse/core'
import { computed, ref } from 'vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import MorphPanel from '@/components/common/MorphPanel.vue'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { api, curlFor } from '@/lib/api'
import { fmt } from '@/lib/format'
import { useLiveStore } from '@/stores/live'
import { AOI_REGION_ID, useQueryStore } from '@/stores/query'
import { type Basemap, useUiStore } from '@/stores/ui'

const query = useQueryStore()
const ui = useUiStore()
const live = useLiveStore()
const { copy, copied } = useClipboard()

const FIRE_SEASON = { from: '-04-01', to: '-10-31' }
const BASEMAPS: { value: Basemap; label: string; icon: typeof MapIcon }[] = [
  { value: 'dark', label: 'Схема', icon: MapIcon },
  { value: 'satellite', label: 'Спутник', icon: Satellite },
]

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
const zoneName = ref('')
const savingZone = ref(false)

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

async function watchZone() {
  if (!query.geometry) return
  savingZone.value = true
  try {
    await api.createZone(zoneName.value.trim() || `${query.regionName}, ${fmt.date(new Date().toISOString())}`, query.geometry, null)
    zoneName.value = ''
    await live.loadZones()
  } finally {
    savingZone.value = false
  }
}
</script>

<template>
  <MorphPanel :open="ui.queryOpen" class="flex max-h-full w-[340px] flex-col" pill-class="w-fit">
    <template #pill>
      <button type="button" class="flex h-12 items-center gap-2.5 pl-4 pr-5 text-sm font-medium" @click="ui.queryOpen = true">
        <SlidersHorizontal class="size-4 text-primary" />
        <span class="max-w-44 truncate">{{ query.regionName }}</span>
      </button>
    </template>

    <header class="flex items-center justify-between px-5 pt-4">
      <span class="label-caps">Запрос</span>
      <Button variant="ghost" size="icon-sm" aria-label="Свернуть панель запроса" @click="ui.queryOpen = false"><ChevronLeft /></Button>
    </header>

    <div class="thin-scroll flex-1 space-y-5 overflow-y-auto px-5 pb-5 pt-2">
      <div>
        <h3 class="mb-2 text-[13px] font-medium">Территория</h3>
        <div class="flex flex-wrap gap-1.5">
          <Button
            v-for="region in regions"
            :key="region.id"
            size="sm"
            :variant="query.regionId === region.id ? 'tonal' : 'outline'"
            @click="query.selectRegion(region.id)"
          >
            {{ region.name }}
          </Button>
        </div>
        <div class="mt-2.5 flex gap-1.5">
          <Button size="sm" :variant="ui.drawMode === 'polygon' ? 'default' : 'secondary'" class="flex-1" @click="toggleDraw('polygon')">
            <component :is="ui.drawMode === 'polygon' ? X : PenTool" />{{ ui.drawMode === 'polygon' ? 'Отмена' : 'Полигон' }}
          </Button>
          <Button size="sm" :variant="ui.drawMode === 'rectangle' ? 'default' : 'secondary'" class="flex-1" @click="toggleDraw('rectangle')">
            <component :is="ui.drawMode === 'rectangle' ? X : Square" />{{ ui.drawMode === 'rectangle' ? 'Отмена' : 'Прямоугольник' }}
          </Button>
        </div>
        <p v-if="ui.drawMode !== 'idle'" class="mt-2 text-xs text-primary">
          {{ ui.drawMode === 'polygon' ? 'Ставьте вершины кликами, замкните контур на первой точке' : 'Кликните два противоположных угла' }}
        </p>
      </div>

      <div>
        <h3 class="mb-2 text-[13px] font-medium">Период</h3>
        <div class="grid grid-cols-2 gap-2">
          <label class="rounded-2xl bg-surface-2 px-3 py-2 text-[11px] text-muted-foreground">
            с
            <input type="date" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none [color-scheme:dark]" :value="query.dateFrom" :max="query.dateTo" @change="query.setPeriod(($event.target as HTMLInputElement).value, query.dateTo)" />
          </label>
          <label class="rounded-2xl bg-surface-2 px-3 py-2 text-[11px] text-muted-foreground">
            по
            <input type="date" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none [color-scheme:dark]" :value="query.dateTo" :min="query.dateFrom" @change="query.setPeriod(query.dateFrom, ($event.target as HTMLInputElement).value)" />
          </label>
        </div>
        <div class="mt-2 flex flex-wrap gap-1.5">
          <Button size="xs" :variant="isFullRange ? 'tonal' : 'outline'" @click="fullRange">Весь охват</Button>
          <Button v-for="year in years" :key="year" size="xs" :variant="activeYear === year ? 'tonal' : 'outline'" @click="pickYear(year)">{{ year }}</Button>
        </div>
      </div>

      <div>
        <h3 class="mb-2 flex items-center gap-1.5 text-[13px] font-medium"><Layers class="size-3.5" />Слои</h3>
        <div class="space-y-2.5 rounded-[20px] bg-surface-2 p-3.5 text-[13px]">
          <label class="flex items-center justify-between gap-3">Гари и степени поражения<Switch v-model="ui.showSeverity" /></label>
          <label class="flex items-center justify-between gap-3">Отфильтрованные срабатывания<Switch v-model="ui.showFiltered" /></label>
          <label class="flex items-center justify-between gap-3">Постоянные источники тепла<Switch v-model="ui.showSources" /></label>
        </div>
        <BubbleTabs v-model="ui.basemap" :options="BASEMAPS" size="sm" stretch class="mt-2.5" />
      </div>

      <div>
        <h3 class="mb-2 text-[13px] font-medium">Следить за этой зоной</h3>
        <div class="flex gap-1.5">
          <input v-model="zoneName" placeholder="Название зоны" class="h-8 min-w-0 flex-1 rounded-full bg-surface-2 px-3.5 text-[13px] outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/50" />
          <Button size="sm" variant="secondary" :disabled="savingZone || !query.geometry" @click="watchZone"><BellPlus />Создать</Button>
        </div>
        <p class="mt-1.5 text-xs leading-snug text-muted-foreground">Новая термоточка в зоне придёт алертом сюда и на webhook (задаётся через API).</p>
      </div>

      <Button v-if="query.params" variant="outline" size="sm" class="w-full font-mono text-xs" @click="copy(curlFor('/api/v1/query', query.params))">
        {{ copied ? 'Скопировано' : 'Скопировать запрос как curl' }}
      </Button>
    </div>
  </MorphPanel>
</template>
