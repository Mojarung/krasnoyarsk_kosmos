<script setup lang="ts">
import { ChevronRight, Crosshair, Siren, X } from '@lucide/vue'
import { computed } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import SparkBars from '@/components/common/SparkBars.vue'
import YandexMapsLink from '@/components/common/YandexMapsLink.vue'
import { denseMonths, fmt, monthRange, plural } from '@/lib/format'
import { TERMS } from '@/lib/glossary'
import type { Report } from '@/lib/types'
import { territoryBounds } from '@/lib/yandex-maps'
import { useQueryStore } from '@/stores/query'
import { type InsightView, useUiStore } from '@/stores/ui'

const props = defineProps<{ report: Report }>()
const emit = defineEmits<{ open: [view: InsightView] }>()
const ui = useUiStore()
const query = useQueryStore()
const mapBounds = computed(() => territoryBounds(query.geometry))

const COLORS = { 1: 'var(--sev-1)', 2: 'var(--sev-2)', 3: 'var(--sev-3)' } as const
const SEVERITY_HINTS = {
  1: 'Слабая степень: растительность восстановится сама',
  2: 'Средняя степень: нужен повторный контроль по снимку',
  3: 'Сильная степень: полное выгорание, в лесу требует посадок',
} as const

const burn = computed(() => props.report.burn)
const hot = computed(() => props.report.hotspots)
const plan = computed(() => props.report.restoration)
const months = computed(() => denseMonths(monthRange(props.report.query.date_from, props.report.query.date_to), burn.value.by_month, (m) => m.month, (m) => m.area_ha))
const peak = computed(() => months.value.reduce<{ month: string; value: number } | null>((best, m) => (m.value > (best?.value ?? 0) ? m : best), null))
const filtered = computed(() => hot.value.technogenic + hot.value.glint)

/**
 * Обзор — одна панель, а не набор карточек. Числа стоят строками на общей
 * линейке, объяснения живут в подсказках. Переход в разбор — по самой строке,
 * поэтому «Подробнее» не повторяется у каждого блока.
 */
const rows = computed(() => [
  {
    key: 'response',
    label: 'Что тушить первым',
    value: '',
    unit: '',
    view: 'response' as InsightView,
    hint: 'План реагирования по свежим очагам: приоритет, прогноз фронта, сёла под угрозой, способ тушения и ближайшая пожарная часть',
  },
  {
    key: 'clusters',
    label: 'Очаги',
    value: fmt.int(hot.value.fire_clusters),
    unit: '',
    view: 'dynamics' as InsightView,
    hint: `${TERMS.cluster}. ${plural(hot.value.fire, ['термоточка', 'термоточки', 'термоточек'])}`,
  },
  {
    key: 'filtered',
    label: 'Ложных выездов',
    value: fmt.int(hot.value.false_dispatches_prevented),
    unit: '',
    view: 'alarms' as InsightView,
    hint: `Заводы, факелы и блики, которые модель не приняла за пожар. ${plural(filtered.value, ['отсеянная термоточка образует', 'отсеянные термоточки образуют', 'отсеянных термоточек образуют'])} ${plural(hot.value.false_dispatches_prevented, ['группу', 'группы', 'групп'])} - столько выездов и сэкономлено`,
  },
  {
    key: 'planting',
    label: 'Нужны посадки',
    value: fmt.ha(plan.value.damage_area_ha),
    unit: 'га',
    view: 'restoration' as InsightView,
    hint: `Восстановится само: ${fmt.ha(plan.value.natural_area_ha)} га. Нажмите, чтобы увидеть мероприятия и оценку затрат`,
  },
])
</script>

<template>
  <div class="px-1">
    <button type="button" class="mb-4 flex w-full items-center justify-between gap-2 rounded-xl bg-secondary px-4 py-3 text-left text-sm font-medium outline-none hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-ring" @click="ui.passportTarget = { type: 'list' }">
      Паспорта пожаров<ChevronRight class="size-4" />
    </button>
    <!-- Итог: число крупнее всего остального, единица рядом, контуры и сцены — справа мелким. -->
    <section v-tip="props.report.method.area">
      <div class="text-[13px] text-muted-foreground">Пройдено огнём</div>
      <div class="mt-0.5 flex items-baseline gap-2">
        <AnimatedNumber :value="burn.total_ha" :format="fmt.ha" class="display-number text-[42px]" />
        <span class="text-base text-muted-foreground">га</span>
        <span v-tip="`${TERMS.contour}. ${TERMS.scene}`" class="ml-auto text-right text-[13px] leading-snug text-muted-foreground">
          {{ plural(burn.contours, ['контур', 'контура', 'контуров']) }}<br>{{ plural(burn.scenes, ['сцена', 'сцены', 'сцен']) }}
        </span>
      </div>

      <!-- Полоса степеней: доля кодируется длиной, число называет её, процента нет —
           он был третьим изображением одной величины и живёт теперь в подсказке. -->
      <div class="mt-4 flex h-3.5 gap-0.5">
        <div
          v-for="item in burn.by_severity"
          :key="item.severity"
          class="h-full rounded-full transition-[flex-grow] duration-700 ease-spring"
          :style="{ flexGrow: burn.total_ha ? Math.max(item.share, 0.004) : 0, flexBasis: 0, background: COLORS[item.severity] }"
        />
      </div>
      <div class="mt-2 grid grid-cols-3 gap-3">
        <div v-for="item in burn.by_severity" :key="item.severity" v-tip="`${SEVERITY_HINTS[item.severity]}. ${fmt.pct(item.share)} от всей площади`">
          <div class="flex items-center gap-1.5 text-[13px] text-muted-foreground"><i class="size-1.5 rounded-full" :style="{ background: COLORS[item.severity] }" />{{ item.label }}</div>
          <div class="mt-0.5 text-[15px] font-semibold tabular-nums">{{ fmt.ha(item.area_ha) }}</div>
        </div>
      </div>
    </section>

    <div v-if="ui.responseCardId" class="flex items-center gap-2 rounded-full bg-primary-container py-1.5 pl-4 pr-1.5 text-xs text-on-primary-container">
      <Siren class="size-3.5 shrink-0" />
      <button type="button" class="min-w-0 flex-1 truncate text-left" @click="emit('open', 'response')">На карте прогноз фронта на 1, 3 и 6 часов · к плану</button>
      <button v-tip="'Убрать прогноз с карты'" type="button" class="flex size-7 shrink-0 items-center justify-center rounded-full hover:bg-black/15" aria-label="Убрать прогноз с карты" @click="ui.responseCardId = null"><X class="size-3.5" /></button>
    </div>

    <!-- Три числа строками: одна линейка, один ритм, переход по самой строке. -->
    <div class="mt-5 border-t border-border/60">
      <button
        v-for="row in rows"
        :key="row.key"
        v-tip="row.hint"
        type="button"
        class="group flex w-full items-baseline gap-3 border-b border-border/60 py-3 text-left outline-none transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-ring/60"
        @click="emit('open', row.view)"
      >
        <span class="min-w-0 flex-1 truncate text-[14px] text-muted-foreground transition-colors duration-200 group-hover:text-foreground">{{ row.label }}</span>
        <span class="shrink-0 text-[19px] font-semibold tabular-nums">{{ row.value }}</span>
        <span v-if="row.unit" class="shrink-0 text-[13px] text-muted-foreground">{{ row.unit }}</span>
        <ChevronRight class="-mr-1 size-4 shrink-0 self-center text-muted-foreground opacity-0 transition-[opacity,transform] duration-200 group-hover:translate-x-0.5 group-hover:opacity-100 group-focus-visible:opacity-100" />
      </button>
    </div>

    <!-- Сезонность: пик словом и числом, форма — спарклайном. -->
    <button
      v-tip="'Площадь гарей по месяцам. Нажмите, чтобы открыть графики крупно'"
      type="button"
      class="group mt-5 flex w-full items-end gap-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      @click="emit('open', 'dynamics')"
    >
      <span class="shrink-0">
        <span class="block text-[13px] text-muted-foreground transition-colors duration-200 group-hover:text-foreground">Когда горело</span>
        <span v-if="peak" class="mt-0.5 block text-[15px] font-semibold">{{ fmt.month(peak.month) }}</span>
        <span v-else class="mt-0.5 block text-[14px] text-muted-foreground">за период гарей нет</span>
      </span>
      <SparkBars class="min-w-0 flex-1" :values="months.map((m) => m.value)" color="var(--sev-2)" :height="58" />
    </button>

    <!-- Крупнейшие гари: дата и площадь, перелёт по нажатию. -->
    <section v-if="burn.largest.length" class="mt-5">
      <div class="text-[13px] text-muted-foreground">Крупнейшие гари</div>
      <div class="mt-1.5 grid grid-cols-2 gap-1.5">
        <button
          v-for="item in burn.largest.slice(0, 2)"
          :key="item.contour_id"
          v-tip="'Перелететь к гари. Клик по контуру откроет паспорт пожара'"
          type="button"
          class="flex items-center gap-2 rounded-full bg-surface-2 px-3 py-2 text-left text-[13px] transition-colors duration-200 hover:bg-surface-3 active:scale-[0.98]"
          @click="ui.flyTarget = { lon: item.lon, lat: item.lat, zoom: 11 }"
        >
          <Crosshair class="size-3.5 shrink-0 text-primary" />
          <span class="min-w-0 flex-1 truncate text-muted-foreground">{{ fmt.date(item.date_post).replace(/\s*г\.$/, '') }}</span>
          <span class="shrink-0 font-semibold tabular-nums">{{ fmt.ha(item.area_ha) }} га</span>
        </button>
      </div>
    </section>
    <YandexMapsLink class="mt-5" :bounds="mapBounds" :place="query.regionName" />
  </div>
</template>
