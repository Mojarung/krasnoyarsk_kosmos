<script setup lang="ts">
import { Download } from '@lucide/vue'
import { useClipboard } from '@vueuse/core'
import { computed, ref } from 'vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { curlFor, download } from '@/lib/api'
import { plural } from '@/lib/format'
import { useQueryStore } from '@/stores/query'

type Layer = 'contours' | 'severity'

const query = useQueryStore()
const { copy, copied } = useClipboard()

const LAYERS = [
  { value: 'contours' as const, label: 'Контуры гарей', hint: 'Внешние границы каждой гари с площадью по степеням' },
  { value: 'severity' as const, label: 'Степени', hint: 'Отдельные полигоны слабой, средней и сильной степени' },
]
const VECTOR = [
  { format: 'geojson', label: 'GeoJSON', hint: 'Для веб-карт и скриптов' },
  { format: 'shp', label: 'Shapefile', hint: 'Архив shp + dbf + prj + cpg для ArcGIS и QGIS' },
  { format: 'gpkg', label: 'GeoPackage', hint: 'Один файл, без ограничений Shapefile на имена полей' },
  { format: 'kml', label: 'KML', hint: 'Для Google Earth' },
]
const REPORT = [
  { format: 'pdf', label: 'PDF', hint: 'Печатная справка с графиками' },
  { format: 'xlsx', label: 'XLSX', hint: 'Excel: показатели, месяцы, типы территории, методика' },
  { format: 'csv', label: 'CSV', hint: 'Таблица показателей' },
  { format: 'json', label: 'JSON', hint: 'Полная справка с методикой, для скриптов и интеграций' },
]

/*
 * Время в шапке справки — по часам того, кто её выгружает: сервер живёт в UTC.
 * Смещение читаем в момент нажатия, иначе вкладка, открытая до перевода часов
 * или переезда в другой пояс, подписала бы справку старым временем.
 */
function tzOffset(): number {
  return -new Date().getTimezoneOffset()
}

const layer = ref<Layer>('contours')
const busy = ref<string | null>(null)
const failure = ref<string | null>(null)

/*
 * Масштаб выгрузки виден до нажатия. На полном охвате слой контуров — это
 * 11 тысяч объектов и десятки мегабайт, слой степеней тяжелее ещё в несколько
 * раз и готовится полминуты. Без этой строки нажатие выглядит как зависание.
 */
const scale = computed(() => {
  const contours = query.report?.burn.contours
  if (!contours) return null
  const heavy = contours > 2000
  if (layer.value === 'contours') {
    // plural уже возвращает число вместе со словом, добавлять fmt.int не надо
    const counted = plural(contours, ['контур', 'контура', 'контуров'])
    return heavy ? `${counted}, десятки мегабайт` : counted
  }
  return heavy ? 'по три полигона на контур, файл в разы тяжелее и готовится до минуты' : 'по три полигона на контур'
})

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
  <Popover>
    <PopoverTrigger as-child>
      <Button v-tip="'Скачать контуры гарей для ГИС и справку по текущему запросу'" variant="default" size="lg" class="flex-1" :disabled="!query.params"><Download />Выгрузить</Button>
    </PopoverTrigger>
    <PopoverContent side="top" align="start" class="w-[388px] rounded-[26px] border-border bg-popover p-4">
      <div class="label-caps mb-2"><span v-tip="'Атрибуты: id контура, степень, площадь в га. Площадь считается в UTM-зоне сцены, координаты в WGS 84'" class="term">Контуры для ГИС</span></div>
      <BubbleTabs v-model="layer" :options="LAYERS" size="sm" stretch />
      <p v-if="scale" class="mt-2 text-[13px] text-muted-foreground">{{ scale }}</p>
      <div class="mt-2.5 flex flex-wrap gap-1.5">
        <Button v-for="item in VECTOR" :key="item.format" v-tip="item.hint" size="sm" variant="secondary" :disabled="busy !== null" @click="save(`/api/v1/burns?layer=${layer}&format=${item.format}`, `burn_${layer}.${item.format}`)">
          {{ busy === `burn_${layer}.${item.format}` ? 'Готовим...' : item.label }}
        </Button>
      </div>

      <div class="label-caps mb-2 mt-4">Аналитическая справка</div>
      <div class="flex flex-wrap gap-1.5">
        <Button v-for="item in REPORT" :key="item.format" v-tip="item.hint" size="sm" variant="secondary" :disabled="busy !== null" @click="save(`/api/v1/report?format=${item.format}&tz_offset=${tzOffset()}`, `report.${item.format}`)">
          {{ busy === `report.${item.format}` ? 'Готовим...' : item.label }}
        </Button>
      </div>

      <Button v-if="query.params" v-tip="'Тот же результат без интерфейса: готовая команда для терминала'" variant="outline" size="sm" class="mt-4 w-full font-mono text-xs" @click="copy(curlFor('/api/v1/query', query.params))">
        {{ copied ? 'Скопировано' : 'Скопировать запрос как curl' }}
      </Button>
      <p v-if="failure" class="mt-2 text-xs text-destructive">{{ failure }}</p>
    </PopoverContent>
  </Popover>
</template>
