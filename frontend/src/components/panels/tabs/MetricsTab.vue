<script setup lang="ts">
import { CloudSun, Gauge, Moon, Thermometer, Timer, Wind } from '@lucide/vue'
import { computed } from 'vue'
import MetricTile from '@/components/common/MetricTile.vue'
import MiniBars from '@/components/common/MiniBars.vue'
import RingGauge from '@/components/common/RingGauge.vue'
import { fmt } from '@/lib/format'
import type { Report } from '@/lib/types'
import { useLiveStore } from '@/stores/live'

const props = defineProps<{ report: Report }>()
const live = useLiveStore()

const quality = computed(() => props.report.quality)
const hotspots = computed(() => props.report.hotspots)
const burnMonths = computed(() => props.report.burn.by_month.map((m) => ({ label: m.month, value: Math.round(m.area_ha) })))
const fireMonths = computed(() => hotspots.value.by_month.map((m) => ({ label: m.month, value: m.n })))
const pipeline = computed(() => Object.entries(live.metrics?.by_kind ?? {}))
</script>

<template>
  <div class="space-y-4">
    <div class="rounded-[24px] bg-surface-2 p-4">
      <div class="flex items-start justify-between gap-3">
        <div>
          <div class="label-caps">Метрика кейса на эталоне</div>
          <div class="mt-1 flex items-baseline gap-2">
            <span class="display-number text-[38px] text-primary">{{ fmt.score(quality?.score) }}</span>
            <span class="text-xs text-muted-foreground">Score</span>
          </div>
        </div>
        <div v-if="quality" class="text-right text-[11px] leading-relaxed text-muted-foreground">
          AF сцен: {{ quality.af_scenes }}<br />BS сцен: {{ quality.bs_scenes }}
        </div>
      </div>
      <div v-if="quality" class="mt-3 grid grid-cols-3 gap-2">
        <RingGauge :value="quality.f1_af" label="F1 горение" color="var(--fire)" />
        <RingGauge :value="quality.iou_burn" label="IoU гарь" color="var(--sev-2)" />
        <RingGauge :value="quality.miou_sev" label="mIoU степени" color="var(--sev-1)" />
      </div>
      <div v-if="quality" class="mt-3 grid grid-cols-5 gap-1 text-center text-[11px] text-muted-foreground">
        <span>P {{ fmt.score(quality.precision_af) }}</span>
        <span>R {{ fmt.score(quality.recall_af) }}</span>
        <span v-for="(value, index) in quality.iou_severity ?? []" :key="index">ст.{{ index + 1 }} {{ fmt.score(value) }}</span>
      </div>
      <p class="mt-2.5 text-[11px] leading-snug text-muted-foreground">
        {{ quality?.note ?? 'В запросе нет сцен с эталонной маской, метрика не считается.' }}
      </p>
    </div>

    <div class="grid grid-cols-3 gap-2">
      <MetricTile label="I4 средняя" :value="fmt.num(hotspots.bt_i4_mean_k)" unit="K" :icon="Thermometer" />
      <MetricTile label="I4 максимум" :value="fmt.num(hotspots.bt_i4_max_k)" unit="K" :icon="Thermometer" tone="fire" />
      <MetricTile label="Ночных" :value="fmt.pct(hotspots.night_share)" :icon="Moon" />
      <MetricTile label="Ветер, ср." :value="fmt.num(hotspots.weather.wind_mean_ms)" unit="м/с" :icon="Wind" />
      <MetricTile label="Воздух" :value="fmt.num(hotspots.weather.t2m_mean_c)" unit="°C" :icon="CloudSun" />
      <MetricTile label="Влажность" :value="fmt.num(hotspots.weather.rh2m_mean)" unit="%" :icon="CloudSun" />
      <MetricTile label="Дней с огнём" :value="fmt.int(hotspots.active_days)" :icon="Gauge" />
      <MetricTile label="Медиана гари" :value="fmt.ha(props.report.burn.median_ha)" unit="га" />
      <MetricTile label="Индекс тяжести" :value="props.report.burn.severity_index?.toFixed(2) ?? '-'" hint="Средняя степень поражения, взвешенная по площади: 1 - слабая, 3 - сильная" tone="tertiary" />
    </div>

    <div class="grid grid-cols-2 gap-2">
      <div class="rounded-[20px] bg-surface-2 p-3">
        <div class="mb-2 text-[11px] text-muted-foreground">Термоточки по месяцам</div>
        <MiniBars :items="fireMonths" color="var(--fire)" />
      </div>
      <div class="rounded-[20px] bg-surface-2 p-3">
        <div class="mb-2 text-[11px] text-muted-foreground">Гари по месяцам, га</div>
        <MiniBars :items="burnMonths" color="var(--sev-2)" />
      </div>
    </div>

    <div v-if="pipeline.length" class="flex items-center gap-3 rounded-full bg-surface-2 px-4 py-2.5 text-xs text-muted-foreground">
      <Timer class="size-3.5 shrink-0 text-primary" />
      <span v-for="[kind, item] in pipeline" :key="kind">{{ kind.toUpperCase() }}: {{ fmt.int(item.mean_ms) }} мс/сцена, p95 {{ fmt.int(item.p95_ms) }}</span>
    </div>
  </div>
</template>
