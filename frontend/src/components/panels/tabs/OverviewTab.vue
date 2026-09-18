<script setup lang="ts">
import { CalendarClock, Crosshair, Flame, ShieldCheck, Sprout } from '@lucide/vue'
import { computed } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import DrillCard from '@/components/common/DrillCard.vue'
import SparkBars from '@/components/common/SparkBars.vue'
import { denseMonths, fmt, monthRange, plural } from '@/lib/format'
import { TERMS } from '@/lib/glossary'
import type { Report } from '@/lib/types'
import { type InsightView, useUiStore } from '@/stores/ui'

const props = defineProps<{ report: Report }>()
const emit = defineEmits<{ open: [view: InsightView] }>()
const ui = useUiStore()

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
</script>

<template>
  <div class="space-y-3">
    <section v-tip="props.report.method.area" class="rounded-[24px] bg-primary-container px-5 py-3.5 text-on-primary-container">
      <div class="label-caps !text-current opacity-70">Пройдено огнём</div>
      <div class="mt-0.5 flex items-baseline gap-2">
        <AnimatedNumber :value="burn.total_ha" :format="fmt.ha" class="display-number text-[38px]" />
        <span class="text-base opacity-80">га</span>
        <span v-tip="`${TERMS.contour}. ${TERMS.scene}`" class="ml-auto text-right text-xs leading-snug opacity-75">{{ plural(burn.contours, ['контур', 'контура', 'контуров']) }}<br />{{ plural(burn.scenes, ['сцена', 'сцены', 'сцен']) }}</span>
      </div>
      <div class="mt-3 flex h-2.5 gap-0.5 overflow-hidden rounded-full bg-black/20">
        <div v-for="item in burn.by_severity" :key="item.severity" class="h-full rounded-full transition-[flex-grow] duration-700 ease-spring" :style="{ flexGrow: burn.total_ha ? Math.max(item.share, 0.004) : 0, flexBasis: 0, background: COLORS[item.severity] }" />
      </div>
      <div class="mt-2 grid grid-cols-3 gap-2 text-xs">
        <div v-for="item in burn.by_severity" :key="item.severity" v-tip="SEVERITY_HINTS[item.severity]">
          <div class="flex items-center gap-1.5 opacity-75"><i class="size-1.5 rounded-full" :style="{ background: COLORS[item.severity] }" />{{ item.label }}</div>
          <div class="mt-0.5 font-semibold tabular-nums">{{ fmt.ha(item.area_ha) }} га <span class="font-normal opacity-70">{{ fmt.pct(item.share) }}</span></div>
        </div>
      </div>
    </section>

    <div class="grid grid-cols-2 gap-2">
      <DrillCard compact title="Очаги пожаров" :icon="Flame" color="var(--fire)" :hint="`${TERMS.cluster}. Нажмите, чтобы открыть графики и статистику`" @open="emit('open', 'dynamics')">
        <span class="text-2xl font-semibold leading-none tabular-nums">{{ fmt.int(hot.fire_clusters) }}</span>
        <span class="mt-1 block truncate text-xs text-muted-foreground">{{ plural(hot.fire, ['термоточка', 'термоточки', 'термоточек']) }}</span>
      </DrillCard>
      <DrillCard compact title="Ложные тревоги" :icon="ShieldCheck" color="var(--technogenic)" hint="Заводы, факелы и блики, которые модель не приняла за пожар. Нажмите, чтобы посмотреть, что отсеяно и почему" @open="emit('open', 'alarms')">
        <span class="text-2xl font-semibold leading-none tabular-nums">{{ fmt.int(filtered) }}</span>
        <span class="mt-1 block truncate text-xs text-muted-foreground">{{ plural(hot.false_dispatches_prevented, ['выезд сэкономлен', 'выезда сэкономлено', 'выездов сэкономлено']) }}</span>
      </DrillCard>
    </div>

    <DrillCard title="Когда горело" :icon="CalendarClock" color="var(--sev-2)" hint="Площадь гарей по месяцам. Нажмите, чтобы открыть графики крупно" @open="emit('open', 'dynamics')">
      <span class="flex items-end gap-3">
        <span class="shrink-0 text-[13px] leading-tight">
          <template v-if="peak"><span class="text-muted-foreground">пик</span> {{ fmt.month(peak.month) }}<br /><span class="font-semibold tabular-nums">{{ fmt.ha(peak.value) }} га</span></template>
          <template v-else><span class="text-muted-foreground">за период гарей нет</span></template>
        </span>
        <SparkBars class="min-w-0 flex-1" :values="months.map((m) => m.value)" color="var(--sev-2)" :height="34" />
      </span>
    </DrillCard>

    <DrillCard title="Что делать с гарями" :icon="Sprout" color="var(--tertiary)" hint="Нажмите, чтобы увидеть мероприятия по каждой гари и оценку затрат" @open="emit('open', 'restoration')">
      <span class="grid grid-cols-2 gap-3 text-[13px] leading-tight">
        <span><span class="block text-lg font-semibold leading-none tabular-nums">{{ fmt.ha(plan.natural_area_ha) }} га</span><span class="mt-1 block text-xs text-muted-foreground">восстановится само</span></span>
        <span><span class="block text-lg font-semibold leading-none tabular-nums text-primary">{{ fmt.ha(plan.damage_area_ha) }} га</span><span class="mt-1 block text-xs text-muted-foreground">нужны посадки</span></span>
      </span>
    </DrillCard>

    <section v-if="burn.largest.length">
      <div class="label-caps mb-1.5">Крупнейшие гари · нажмите, чтобы перелететь</div>
      <div class="grid grid-cols-2 gap-1.5">
        <button
          v-for="item in burn.largest.slice(0, 2)"
          :key="item.contour_id"
          v-tip="'Перелететь к гари. Клик по контуру на карте откроет сравнение до и после'"
          type="button"
          class="flex items-center gap-2 rounded-full bg-surface-2 px-3 py-2 text-left text-xs transition-colors duration-200 hover:bg-surface-3 active:scale-[0.98]"
          @click="ui.flyTarget = { lon: item.lon, lat: item.lat, zoom: 11 }"
        >
          <Crosshair class="size-3.5 shrink-0 text-primary" />
          <span class="min-w-0 flex-1 truncate text-muted-foreground">{{ fmt.date(item.date_post).replace(/\s*г\.$/, '') }}</span>
          <span class="shrink-0 font-semibold tabular-nums">{{ fmt.ha(item.area_ha) }} га</span>
        </button>
      </div>
    </section>
  </div>
</template>
