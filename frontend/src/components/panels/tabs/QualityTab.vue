<script setup lang="ts">
import { Timer, TriangleAlert } from '@lucide/vue'
import { computed } from 'vue'
import RingGauge from '@/components/common/RingGauge.vue'
import StatRows, { type StatRow } from '@/components/common/StatRows.vue'
import { fmt } from '@/lib/format'
import { TERMS } from '@/lib/glossary'
import type { Report } from '@/lib/types'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'

const props = defineProps<{ report: Report }>()
const live = useLiveStore()
const query = useQueryStore()

const SCORE_HINT = 'Score = 0.35 F1_af + 0.35 IoU_burn + 0.30 mIoU_sev, микро-усреднение по пикселям, как в постановке кейса'
const KIND_LABELS: Record<string, string> = { af: 'Горение, VIIRS', bs: 'Гари, Sentinel' }

const quality = computed(() => props.report.quality)
const models = computed(() => query.meta?.data.models ?? [])
const details = computed<StatRow[]>(() => {
  const q = quality.value
  if (!q) return []
  const severity = q.iou_severity ?? []
  return [
    { label: 'Горение: точность', value: fmt.score(q.precision_af), hint: TERMS.precision },
    { label: 'Горение: полнота', value: fmt.score(q.recall_af), hint: TERMS.recall },
    { label: 'Гари: IoU слабой степени', value: fmt.score(severity[0]), hint: TERMS.iou },
    { label: 'Гари: IoU средней степени', value: fmt.score(severity[1]), hint: TERMS.iou },
    { label: 'Гари: IoU сильной степени', value: fmt.score(severity[2]), hint: TERMS.iou },
    { label: 'Сцен с эталоном в запросе', value: `${q.af_scenes} AF, ${q.bs_scenes} BS`, hint: TERMS.reference },
  ]
})
const pipeline = computed<StatRow[]>(() =>
  Object.entries(live.metrics?.by_kind ?? {}).map(([kind, item]) => ({
    label: KIND_LABELS[kind] ?? kind,
    value: `${fmt.int(item.mean_ms)} мс, p95 ${fmt.int(item.p95_ms)} мс`,
    hint: `${TERMS.p95}. В него входит чтение из S3, модель, векторизация и запись в PostGIS`,
  })),
)
</script>

<template>
  <div class="grid items-start gap-4 @2xl:grid-cols-2 @4xl:grid-cols-3">
    <div class="space-y-4">
    <div v-if="quality" class="rounded-[24px] bg-surface-2 p-4">
      <div v-tip="SCORE_HINT" class="flex items-baseline gap-2">
        <span class="display-number text-[38px] text-primary">{{ fmt.score(quality.score) }}</span>
        <span class="text-xs text-muted-foreground">итоговый Score из 1</span>
      </div>
      <div class="mt-3 grid grid-cols-3 gap-2">
        <RingGauge v-tip="`${TERMS.f1}. Вес в итоговом Score 0,35`" :value="quality.f1_af" label="F1 горение" color="var(--fire)" />
        <RingGauge v-tip="`${TERMS.iou}. Здесь сравниваются контуры гарей, вес в итоговом Score 0,35`" :value="quality.iou_burn" label="IoU гарь" color="var(--sev-2)" />
        <RingGauge v-tip="`Средний IoU по трём степеням поражения. ${TERMS.iou}. Вес в итоговом Score 0,30`" :value="quality.miou_sev" label="mIoU степени" color="var(--sev-1)" />
      </div>
    </div>
    <p v-else class="rounded-[22px] bg-surface-2 p-4 text-[13px] leading-snug text-muted-foreground">В запросе нет сцен с эталонной маской, поэтому сравнить модели не с чем. Выберите территорию и период, где есть размеченные сцены.</p>

    <p v-if="quality" class="flex gap-2 rounded-[18px] bg-tertiary-container/50 px-3.5 py-2.5 text-xs leading-snug">
      <TriangleAlert class="mt-0.5 size-3.5 shrink-0" />
      <span>Модель горения обучена на этих же сценах, поэтому её F1 здесь завышен. Честная оценка на кросс-валидации по территории: 0,960.</span>
    </p>
    </div>

    <StatRows v-if="details.length" title="По компонентам" :rows="details" />
    <div class="space-y-4">
    <StatRows v-if="pipeline.length" title="Скорость конвейера" :rows="pipeline" />

    <div v-if="models.length" class="flex items-start gap-2 text-xs text-muted-foreground">
      <Timer class="mt-0.5 size-3.5 shrink-0" />
      <span>Модели в работе: {{ models.join(', ') }}</span>
    </div>
    </div>
  </div>
</template>
