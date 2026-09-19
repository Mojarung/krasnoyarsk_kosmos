<script setup lang="ts">
import { Flame, Wind } from '@lucide/vue'
import { computed } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import BarList, { type BarListItem } from '@/components/common/BarList.vue'
import StatRows, { type StatRow } from '@/components/common/StatRows.vue'
import { fmt } from '@/lib/format'
import type { Report } from '@/lib/types'

const SPECIES_TONE: Record<string, string> = {
  co2: 'var(--sev-3)',
  co: 'var(--sev-2)',
  ch4: 'var(--fire)',
  pm25: 'var(--glint)',
}

const props = defineProps<{ report: Report }>()
const emissions = computed(() => props.report.emissions)
const peak = computed(() => Math.max(1, ...emissions.value.species.map((s) => s.tonnes)))

const byLandcover = computed<BarListItem[]>(() =>
  emissions.value.by_landcover.map((row) => ({
    key: row.landcover,
    label: row.label,
    value: Math.round(row.dry_matter_t),
    hint: `${fmt.ha(row.area_ha)} га при запасе ${fmt.num(row.load_t_ha)} т/га`,
  })),
)

const bySeverity = computed<StatRow[]>(() =>
  emissions.value.by_severity.map((row) => ({
    label: `${row.label} степень`,
    value: `${fmt.int(Math.round(row.dry_matter_t))} т`,
    hint: `Сгорает ${fmt.pct(row.completeness)} горючего материала на этой площади`,
  })),
)
</script>

<template>
  <div class="grid items-start gap-4 @2xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
    <div class="space-y-3">
      <div class="grid grid-cols-2 gap-2 @2xl:grid-cols-1">
        <div v-tip="'Сколько сухой биомассы сгорело: основа всех расчётов ниже'" class="rounded-[24px] bg-surface-2 px-4 py-3.5">
          <div class="flex items-center gap-1.5 text-[11px] opacity-75"><Flame class="size-3.5" />Сгорело биомассы</div>
          <div class="mt-1 flex items-baseline gap-1.5">
            <AnimatedNumber :value="emissions.dry_matter_t" :format="fmt.compact" class="display-number text-[28px]" />
            <span class="text-sm opacity-70">т</span>
          </div>
        </div>
        <div v-tip="'Парниковый след пожара: CO₂ плюс метан по потенциалу потепления за 100 лет'" class="rounded-[24px] bg-primary-container px-4 py-3.5 text-on-primary-container">
          <div class="flex items-center gap-1.5 text-[11px] opacity-75"><Wind class="size-3.5" />CO₂-эквивалент</div>
          <div class="mt-1 flex items-baseline gap-1.5">
            <AnimatedNumber :value="emissions.co2e_t" :format="fmt.compact" class="display-number text-[28px]" />
            <span class="text-sm opacity-70">т</span>
          </div>
        </div>
      </div>
      <StatRows title="Сгорело по степени поражения" :rows="bySeverity" />
      <p class="text-[11px] leading-snug text-muted-foreground">{{ emissions.disclaimer }}</p>
    </div>

    <div class="space-y-4">
      <div>
        <div class="label-caps mb-1.5"><span v-tip="emissions.method" class="term">Выброшено в атмосферу</span></div>
        <div class="gap-1.5 @4xl:columns-2">
          <div v-for="item in emissions.species" :key="item.key" v-tip="item.about" class="mb-1.5 block w-full break-inside-avoid rounded-[20px] bg-surface-2 px-4 py-3">
            <div class="flex items-start justify-between gap-3">
              <span class="text-[13px] leading-snug">{{ item.label }}<span class="ml-1.5 opacity-60">{{ item.name }}</span></span>
              <span class="shrink-0 text-[13px] font-semibold tabular-nums">{{ fmt.compact(item.tonnes) }} т</span>
            </div>
            <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
              <div class="h-full rounded-full transition-[width] duration-700 ease-spring" :style="{ width: `${(item.tonnes / peak) * 100}%`, background: SPECIES_TONE[item.key] ?? 'var(--fire)' }" />
            </div>
          </div>
        </div>
      </div>
      <BarList title="Откуда взялась биомасса, т" hint="Запас горючего материала зависит от типа территории: гектар леса даёт 50 тонн сухой массы, гектар степи - 5" unit="т" color="var(--sev-2)" :items="byLandcover" :format="fmt.compact" />
      <p class="text-[11px] leading-snug text-muted-foreground">{{ emissions.sources }}</p>
    </div>
  </div>
</template>
