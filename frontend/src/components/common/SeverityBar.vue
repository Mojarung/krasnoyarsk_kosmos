<script setup lang="ts">
import { computed } from 'vue'
import { fmt } from '@/lib/format'
import type { SeverityShare } from '@/lib/types'

const props = defineProps<{ items: SeverityShare[] }>()

const COLORS = { 1: 'var(--sev-1)', 2: 'var(--sev-2)', 3: 'var(--sev-3)' } as const
const HINTS = {
  1: 'Слабая степень: растительность восстановится сама',
  2: 'Средняя степень: нужен повторный контроль по снимку',
  3: 'Сильная степень: полное выгорание, в лесу требует посадок',
} as const
const total = computed(() => props.items.reduce((sum, item) => sum + item.area_ha, 0))
</script>

<template>
  <div>
    <div class="flex h-3 gap-0.5 overflow-hidden rounded-full bg-surface-3">
      <div
        v-for="item in props.items"
        :key="item.severity"
        class="h-full rounded-full transition-[flex-grow] duration-700 ease-spring"
        :style="{ flexGrow: total ? Math.max(item.share, 0.004) : 0, flexBasis: 0, background: COLORS[item.severity] }"
      />
    </div>
    <div class="mt-2.5 space-y-1.5">
      <div v-for="item in props.items" :key="item.severity" v-tip="HINTS[item.severity]" class="flex items-center gap-2 text-[13px]">
        <span class="size-2 shrink-0 rounded-full" :style="{ background: COLORS[item.severity] }" />
        <span class="flex-1 text-muted-foreground">{{ item.label }}</span>
        <span class="font-medium tabular-nums">{{ fmt.ha(item.area_ha) }} га</span>
        <span class="w-12 text-right text-xs text-muted-foreground tabular-nums">{{ fmt.pct(item.share) }}</span>
      </div>
    </div>
  </div>
</template>
