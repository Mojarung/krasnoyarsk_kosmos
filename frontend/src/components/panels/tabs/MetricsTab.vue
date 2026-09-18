<script setup lang="ts">
import { Timer } from '@lucide/vue'
import { computed } from 'vue'
import MiniBars from '@/components/common/MiniBars.vue'
import RingGauge from '@/components/common/RingGauge.vue'
import StatRows, { type StatRow } from '@/components/common/StatRows.vue'
import { fmt } from '@/lib/format'
import type { Report } from '@/lib/types'
import { useLiveStore } from '@/stores/live'

const props = defineProps<{ report: Report }>()
const live = useLiveStore()

const SCORE_HINT = 'Score = 0.35 F1_af + 0.35 IoU_burn + 0.30 mIoU_sev, микро-усреднение по пикселям, как в постановке кейса'

const quality = computed(() => props.report.quality)
const burnMonths = computed(() => props.report.burn.by_month.map((m) => ({ label: m.month, value: Math.round(m.area_ha) })))
const fireMonths = computed(() => props.report.hotspots.by_month.map((m) => ({ label: m.month, value: m.n })))
const pipeline = computed(() => Object.entries(live.metrics?.by_kind ?? {}))

const hotspotRows = computed<StatRow[]>(() => {
  const h = props.report.hotspots
  return [
    { label: 'Яркостная температура I4, средняя', value: `${fmt.num(h.bt_i4_mean_k)} K`, hint: 'Канал 3,74 мкм, основной для детекции горения' },
    { label: 'I4, максимум', value: `${fmt.num(h.bt_i4_max_k)} K`, hint: 'Канал насыщается около 367 K' },
    { label: 'Ночных детекций', value: fmt.pct(h.night_share), hint: 'Доля термоточек с зенитным углом Солнца больше 88 градусов' },
    { label: 'Дней с огнём', value: fmt.int(h.active_days) },
  ]
})
const weatherRows = computed<StatRow[]>(() => {
  const w = props.report.hotspots.weather
  return [
    { label: 'Ветер, средний и максимум', value: `${fmt.num(w.wind_mean_ms)} / ${fmt.num(w.wind_max_ms)} м/с`, hint: 'ERA5-Land на момент пролёта, по пикселям природных пожаров' },
    { label: 'Температура воздуха', value: `${fmt.num(w.t2m_mean_c)} °C` },
    { label: 'Влажность', value: `${fmt.num(w.rh2m_mean)} %` },
  ]
})
const burnRows = computed<StatRow[]>(() => {
  const b = props.report.burn
  return [
    { label: 'Контур: медиана и максимум', value: `${fmt.ha(b.median_ha)} / ${fmt.ha(b.max_ha)} га` },
    { label: 'Доля территории запроса', value: fmt.pct(b.burned_share), hint: `Площадь запроса ${fmt.int(b.query_area_km2)} км²` },
    { label: 'Индекс тяжести', value: b.severity_index?.toFixed(2) ?? '-', hint: 'Средняя степень, взвешенная по площади: 1 слабая, 3 сильная' },
  ]
})
</script>

<template>
  <div class="space-y-4">
    <div class="rounded-[24px] bg-surface-2 p-4">
      <div class="flex items-start justify-between gap-3">
        <div v-tip="SCORE_HINT">
          <div class="label-caps">Метрика кейса на эталоне</div>
          <div class="mt-1 flex items-baseline gap-2">
            <span class="display-number text-[38px] text-primary">{{ fmt.score(quality?.score) }}</span>
            <span class="text-xs text-muted-foreground">Score</span>
          </div>
        </div>
        <div v-if="quality" class="text-right text-[11px] leading-relaxed text-muted-foreground">AF сцен: {{ quality.af_scenes }}<br />BS сцен: {{ quality.bs_scenes }}</div>
      </div>
      <div v-if="quality" class="mt-3 grid grid-cols-3 gap-2">
        <RingGauge v-tip="`Точность ${fmt.score(quality.precision_af)}, полнота ${fmt.score(quality.recall_af)}`" :value="quality.f1_af" label="F1 горение" color="var(--fire)" />
        <RingGauge v-tip="'IoU бинарного контура гари'" :value="quality.iou_burn" label="IoU гарь" color="var(--sev-2)" />
        <RingGauge v-tip="`IoU по степеням: ${(quality.iou_severity ?? []).map((v) => fmt.score(v)).join(' / ')}`" :value="quality.miou_sev" label="mIoU степени" color="var(--sev-1)" />
      </div>
      <p v-else class="mt-2 text-xs leading-snug text-muted-foreground">В запросе нет сцен с эталонной маской, метрика не считается.</p>
    </div>

    <StatRows title="Термоточки пожаров" :rows="hotspotRows" />
    <StatRows title="Погода в момент детекции" :rows="weatherRows" />
    <StatRows title="Гари" :rows="burnRows" />

    <div class="grid grid-cols-2 gap-2">
      <div class="rounded-[20px] bg-surface-2 p-3">
        <div class="mb-2 text-[11px] text-muted-foreground">Термоточки по месяцам</div>
        <MiniBars :items="fireMonths" color="var(--fire)" :height="44" />
      </div>
      <div class="rounded-[20px] bg-surface-2 p-3">
        <div class="mb-2 text-[11px] text-muted-foreground">Гари по месяцам, га</div>
        <MiniBars :items="burnMonths" color="var(--sev-2)" :height="44" />
      </div>
    </div>

    <div v-if="pipeline.length" v-tip="'Среднее время обработки одной сцены конвейером, включая инференс, векторизацию и запись в PostGIS'" class="flex items-center gap-3 rounded-full bg-surface-2 px-4 py-2.5 text-xs text-muted-foreground">
      <Timer class="size-3.5 shrink-0 text-primary" />
      <span v-for="[kind, item] in pipeline" :key="kind">{{ kind.toUpperCase() }}: {{ fmt.int(item.mean_ms) }} мс на сцену</span>
    </div>
  </div>
</template>
