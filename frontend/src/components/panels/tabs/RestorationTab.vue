<script setup lang="ts">
import { Sprout, TreePine } from '@lucide/vue'
import { computed, ref } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import { fmt } from '@/lib/format'
import type { Report } from '@/lib/types'

const BREAKDOWN_ROWS = 5

const props = defineProps<{ report: Report }>()
const plan = computed(() => props.report.restoration)
const peak = computed(() => Math.max(1, ...plan.value.items.map((i) => i.area_ha)))
const opened = ref<string | null>(null)
</script>

<template>
  <div class="grid items-start gap-4 @2xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
    <div class="space-y-3">
      <div class="grid grid-cols-2 gap-2 @2xl:grid-cols-1">
        <div v-tip="'Слабая степень и травяные территории: растительность вернётся сама'" class="rounded-[24px] bg-tertiary-container/70 px-4 py-3.5">
          <div class="flex items-center gap-1.5 text-[13px] opacity-90"><Sprout class="size-3.5" />Восстановится само</div>
          <div class="mt-1 flex items-baseline gap-1.5"><AnimatedNumber :value="plan.natural_area_ha" :format="fmt.ha" class="display-number text-[28px]" /><span class="text-sm opacity-90">га</span></div>
        </div>
        <div v-tip="'Здесь лес сам не вернётся. Эта площадь идёт в расчёт ущерба'" class="rounded-[24px] bg-primary-container px-4 py-3.5 text-on-primary-container">
          <div class="flex items-center gap-1.5 text-[13px] opacity-90"><TreePine class="size-3.5" />Нужны посадки</div>
          <div class="mt-1 flex items-baseline gap-1.5"><AnimatedNumber :value="plan.damage_area_ha" :format="fmt.ha" class="display-number text-[28px]" /><span class="text-sm opacity-90">га</span></div>
        </div>
      </div>
      <div class="flex items-center justify-between gap-3 rounded-full bg-surface-3 px-4 py-2.5 text-[13px]">
        <span class="text-muted-foreground">Ориентировочные затраты</span>
        <span class="font-semibold tabular-nums">{{ fmt.money(plan.total_cost, plan.currency) }}</span>
      </div>
      <p class="text-[11px] leading-snug text-muted-foreground">{{ plan.disclaimer }}</p>
    </div>

    <div>
      <div class="label-caps mb-1.5">Что делать и на какой площади</div>
      <div class="gap-1.5 @4xl:columns-2">
        <button
          v-for="item in plan.items"
          :key="item.action"
          type="button"
          class="mb-1.5 block w-full break-inside-avoid rounded-[20px] bg-surface-2 px-4 py-3 text-left transition-colors duration-300 hover:bg-surface-3 @2xl:cursor-default"
          :aria-expanded="opened === item.action"
          @click="opened = opened === item.action ? null : item.action"
        >
          <div class="flex items-start justify-between gap-3">
            <span class="text-[13px] leading-snug">{{ item.label }}</span>
            <span class="shrink-0 text-[13px] font-semibold tabular-nums">{{ fmt.ha(item.area_ha) }} га</span>
          </div>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
            <div class="h-full rounded-full transition-[width] duration-700 ease-spring" :class="item.counts_as_damage ? 'bg-primary' : 'bg-tertiary'" :style="{ width: `${(item.area_ha / peak) * 100}%` }" />
          </div>
          <div v-if="item.cost" class="mt-1.5 text-xs text-muted-foreground">{{ fmt.money(item.cost, plan.currency) }} при {{ fmt.int(item.rate_per_ha) }} за га</div>
          <div class="mt-2.5 space-y-1 border-t border-border/60 pt-2.5" :class="opened === item.action ? 'block' : 'hidden @2xl:block'">
            <div v-for="row in item.breakdown.slice(0, BREAKDOWN_ROWS)" :key="row.landcover_label + row.severity" class="flex justify-between gap-3 text-xs text-muted-foreground">
              <span>{{ row.landcover_label }}, {{ row.severity_label }}</span><span class="shrink-0 tabular-nums">{{ fmt.ha(row.area_ha) }} га</span>
            </div>
          </div>
        </button>
      </div>
    </div>
  </div>
</template>
