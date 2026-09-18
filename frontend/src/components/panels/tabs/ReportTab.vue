<script setup lang="ts">
import { Crosshair, Download, Flame, ShieldCheck } from '@lucide/vue'
import { useClipboard } from '@vueuse/core'
import { ref } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import MetricTile from '@/components/common/MetricTile.vue'
import SeverityBar from '@/components/common/SeverityBar.vue'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { curlFor, download } from '@/lib/api'
import { fmt, plural } from '@/lib/format'
import type { Report } from '@/lib/types'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ report: Report }>()
const query = useQueryStore()
const ui = useUiStore()
const { copy, copied } = useClipboard()

type Layer = 'contours' | 'severity'
const layer = ref<Layer>('contours')
const busy = ref<string | null>(null)
const failure = ref<string | null>(null)

const LAYERS = [
  { value: 'contours' as const, label: 'Контуры гарей' },
  { value: 'severity' as const, label: 'Степени' },
]
const VECTOR = [
  { format: 'geojson', label: 'GeoJSON', hint: 'Для веб-карт и скриптов' },
  { format: 'shp', label: 'Shapefile', hint: 'Архив shp + dbf + prj + cpg для ArcGIS и QGIS' },
  { format: 'gpkg', label: 'GeoPackage', hint: 'Один файл, без ограничений Shapefile на имена полей' },
  { format: 'kml', label: 'KML', hint: 'Для Google Earth' },
]
const REPORT = [
  { format: 'json', hint: 'Полная справка с методикой, машиночитаемо' },
  { format: 'csv', hint: 'Таблица показателей' },
  { format: 'xlsx', hint: 'Excel: показатели, термоточки по дням, методика' },
  { format: 'pdf', hint: 'Печатная справка' },
]
const FILTER_HINT = 'Техногенные источники и блики, которые не попали в пожары. Подробности на вкладке Фильтр'

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
  <div class="space-y-4">
    <div v-tip="props.report.method.area" class="rounded-[24px] bg-primary-container px-5 py-4 text-on-primary-container">
      <div class="label-caps !text-current opacity-70">Пройдено огнём</div>
      <div class="mt-1 flex items-baseline gap-2">
        <AnimatedNumber :value="props.report.burn.total_ha" :format="fmt.ha" class="display-number text-[42px]" />
        <span class="text-lg opacity-80">га</span>
      </div>
      <div class="mt-1.5 text-xs opacity-75">{{ plural(props.report.burn.contours, ['контур', 'контура', 'контуров']) }} в {{ plural(props.report.burn.scenes, ['сцене', 'сценах', 'сценах']) }}</div>
    </div>

    <SeverityBar :items="props.report.burn.by_severity" />

    <div class="grid grid-cols-2 gap-2">
      <MetricTile label="Очагов пожаров" :value="fmt.int(props.report.hotspots.fire_clusters)" :sub="plural(props.report.hotspots.fire, ['термоточка', 'термоточки', 'термоточек'])" :icon="Flame" color="var(--fire)" :hint="props.report.method.hotspots" />
      <MetricTile
        label="Отсеяно срабатываний"
        :value="fmt.int(props.report.hotspots.technogenic + props.report.hotspots.glint)"
        :sub="plural(props.report.hotspots.false_dispatches_prevented, ['ложный выезд', 'ложных выезда', 'ложных выездов'])"
        :icon="ShieldCheck"
        color="var(--technogenic)"
        :hint="FILTER_HINT"
      />
    </div>

    <div v-if="props.report.burn.largest.length">
      <div class="label-caps mb-1.5">Крупнейшие гари</div>
      <div class="space-y-1">
        <button
          v-for="item in props.report.burn.largest.slice(0, 3)"
          :key="item.contour_id"
          v-tip="'Перелететь к гари. Клик по контуру на карте откроет сравнение до и после'"
          type="button"
          class="flex w-full items-center justify-between rounded-full bg-surface-2 px-3.5 py-2 text-[13px] transition-colors duration-200 hover:bg-surface-3 active:scale-[0.99]"
          @click="ui.flyTarget = { lon: item.lon, lat: item.lat, zoom: 11 }"
        >
          <span class="flex items-center gap-2"><Crosshair class="size-3.5 text-primary" />{{ fmt.date(item.date_post) }}</span>
          <span class="font-medium tabular-nums">{{ fmt.ha(item.area_ha) }} га</span>
        </button>
      </div>
    </div>

    <div class="sticky bottom-0 -mx-4 -mb-4 bg-gradient-to-t from-surface-1 from-60% to-transparent px-4 pb-4 pt-3">
    <Popover>
      <PopoverTrigger as-child>
        <Button v-tip="'Контуры в GeoJSON, Shapefile, GeoPackage, KML и справка в JSON, CSV, XLSX, PDF'" variant="tonal" class="w-full"><Download />Выгрузить контуры и справку</Button>
      </PopoverTrigger>
      <PopoverContent side="top" align="end" class="w-[380px] rounded-[26px] border-border bg-popover p-4">
        <div class="label-caps mb-2">Векторные контуры</div>
        <BubbleTabs v-model="layer" :options="LAYERS" size="sm" stretch />
        <div class="mt-2.5 flex flex-wrap gap-1.5">
          <Button v-for="item in VECTOR" :key="item.format" v-tip="item.hint" size="sm" variant="secondary" :disabled="busy !== null" @click="save(`/api/v1/burns?layer=${layer}&format=${item.format}`, `burn_${layer}.${item.format}`)">
            {{ busy === `burn_${layer}.${item.format}` ? 'Готовим...' : item.label }}
          </Button>
        </div>
        <div class="label-caps mb-2 mt-4">Аналитическая справка</div>
        <div class="flex flex-wrap gap-1.5">
          <Button v-for="item in REPORT" :key="item.format" v-tip="item.hint" size="sm" variant="secondary" class="uppercase" :disabled="busy !== null" @click="save(`/api/v1/report?format=${item.format}`, `report.${item.format}`)">
            {{ busy === `report.${item.format}` ? '...' : item.format }}
          </Button>
        </div>
        <Button v-if="query.params" v-tip="'Тот же результат без интерфейса: готовая команда для терминала'" variant="outline" size="sm" class="mt-4 w-full font-mono text-xs" @click="copy(curlFor('/api/v1/query', query.params))">
          {{ copied ? 'Скопировано' : 'Скопировать запрос как curl' }}
        </Button>
        <p v-if="failure" class="mt-2 text-xs text-destructive">{{ failure }}</p>
        <p class="mt-3 text-[11px] leading-snug text-muted-foreground">Атрибуты: id контура, степень, площадь в га. Площадь считается в UTM-зоне сцены, координаты в WGS 84.</p>
      </PopoverContent>
    </Popover>
    </div>
  </div>
</template>
