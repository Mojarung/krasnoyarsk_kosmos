<script setup lang="ts">
import { computed, ref } from 'vue'
import BarList, { type BarListItem } from '@/components/common/BarList.vue'
import MonthBars from '@/components/common/MonthBars.vue'
import StatRows, { type StatRow } from '@/components/common/StatRows.vue'
import { denseMonths, fmt, monthRange } from '@/lib/format'
import { LANDCOVER_HINTS, SATELLITE_INFO, TERMS } from '@/lib/glossary'
import type { Report } from '@/lib/types'

const props = defineProps<{ report: Report }>()

const FIRE_HINT = 'Число природных термоточек VIIRS 375 м по месяцу пролёта, техногенные и блики исключены. Наведите курсор или используйте стрелки, чтобы пройти по месяцам'
const BURN_HINT = 'Площадь гарей, обрезанная по контуру запроса, по месяцу послепожарного снимка. Месяцы без съёмки показаны нулём'

/** Общая ось месяцев для обоих графиков: пропуски заполняем нулями, иначе столбики не сопоставимы по времени. */
const months = computed(() => monthRange(props.report.query.date_from, props.report.query.date_to))
const fireMonths = computed(() => denseMonths(months.value, props.report.hotspots.by_month, (m) => m.month, (m) => m.n))
const burnMonths = computed(() => denseMonths(months.value, props.report.burn.by_month, (m) => m.month, (m) => m.area_ha))

/**
 * Курсор один на оба графика. Величины несопоставимы по масштабу — вторая ось
 * была бы враньём, — поэтому это малые кратные: общая ось времени, общий курсор,
 * и сравнение читается по вертикали, а не по наложению.
 */
const cursor = ref<number | null>(null)

const fireLandcover = computed<BarListItem[]>(() => props.report.hotspots.by_landcover.map((l) => ({ key: l.landcover, label: l.label, value: l.n, hint: LANDCOVER_HINTS[l.label] })))
const burnLandcover = computed<BarListItem[]>(() => props.report.burn.by_landcover.map((l) => ({ key: l.landcover, label: l.label, value: Math.round(l.area_ha), hint: LANDCOVER_HINTS[l.label] })))
const satellites = computed<BarListItem[]>(() => Object.entries(props.report.hotspots.by_satellite).map(([name, n]) => {
    const info = SATELLITE_INFO[name.toUpperCase()]
    return { key: name, label: info?.label ?? name.toUpperCase(), value: n, hint: info?.hint }
  }))

const hotspotRows = computed<StatRow[]>(() => {
  const h = props.report.hotspots
  return [
    { label: 'Температура термоточек, средняя', value: `${fmt.num(h.bt_i4_mean_k)} K`, hint: TERMS.btMean },
    { label: 'Самая горячая термоточка', value: `${fmt.num(h.bt_i4_max_k)} K`, hint: TERMS.btMax },
    { label: 'Замечено ночью', value: fmt.pct(h.night_share), hint: TERMS.nightShare },
    { label: 'Дней с огнём', value: fmt.int(h.active_days), hint: TERMS.activeDays },
  ]
})
const weatherRows = computed<StatRow[]>(() => {
  const w = props.report.hotspots.weather
  return [
    { label: 'Ветер, средний и максимум', value: `${fmt.num(w.wind_mean_ms)} / ${fmt.num(w.wind_max_ms)} м/с`, hint: TERMS.wind },
    { label: 'Температура воздуха', value: `${fmt.num(w.t2m_mean_c)} °C`, hint: TERMS.temperature },
    { label: 'Влажность', value: `${fmt.num(w.rh2m_mean)} %`, hint: TERMS.humidity },
  ]
})
const burnRows = computed<StatRow[]>(() => {
  const b = props.report.burn
  return [
    { label: 'Гарь: типичная и наибольшая', value: `${fmt.ha(b.median_ha)} / ${fmt.ha(b.max_ha)} га`, hint: TERMS.contourSize },
    { label: 'Доля территории запроса', value: fmt.pct(b.burned_share), hint: `${TERMS.burnedShare}. Площадь территории: ${fmt.int(b.query_area_km2)} км²` },
    { label: 'Средняя степень поражения', value: b.severity_index?.toFixed(2) ?? '—', hint: TERMS.severityIndex },
  ]
})
</script>

<template>
  <div class="grid items-start gap-6 @4xl:grid-cols-3">
    <div class="space-y-6 @4xl:col-span-2">
      <!-- Одна ось времени, два ряда: огонь сверху, гарь снизу. Курсор общий. -->
      <section class="space-y-6 rounded-[20px] bg-surface-2 px-4 pb-4 pt-3.5">
        <MonthBars
          v-model:cursor="cursor"
          title="Термоточки пожаров по месяцам"
          unit="точек"
          color="var(--fire)"
          :items="fireMonths"
          :hint="FIRE_HINT"
          :axis="false"
        />
        <MonthBars
          v-model:cursor="cursor"
          title="Площадь гарей по месяцам"
          unit="га"
          color="var(--sev-2)"
          :items="burnMonths"
          :hint="BURN_HINT"
          :format="fmt.ha"
        />
      </section>

      <div class="grid items-start gap-6 @2xl:grid-cols-2">
        <BarList title="Термоточки по типу территории" :hint="TERMS.landcover" unit="точек" color="var(--fire)" :items="fireLandcover" />
        <BarList title="Гари по типу территории" :hint="TERMS.landcover" unit="га" color="var(--sev-2)" :items="burnLandcover" :format="fmt.ha" />
      </div>
    </div>

    <div class="grid items-start gap-6 @2xl:grid-cols-2 @4xl:grid-cols-1">
      <!-- Спутник — не пожарные данные, поэтому неогненный акцент. -->
      <BarList title="Термоточки по спутникам" :hint="TERMS.satellites" unit="точек" color="var(--primary)" :items="satellites" :limit="4" />
      <StatRows title="Термоточки пожаров" :hint="TERMS.hotspot" :rows="hotspotRows" />
      <StatRows title="Погода, когда горело" :rows="weatherRows" />
      <StatRows title="Гари" :hint="TERMS.contour" :rows="burnRows" />
    </div>
  </div>
</template>
