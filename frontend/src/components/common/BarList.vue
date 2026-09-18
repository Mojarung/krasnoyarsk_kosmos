<script setup lang="ts">
import { computed } from 'vue'
import { fmt } from '@/lib/format'

export interface BarListItem {
  key: string
  label: string
  value: number
  hint?: string
}

const props = withDefaults(
  defineProps<{
    title: string
    hint?: string
    items: BarListItem[]
    unit: string
    color?: string
    limit?: number
    format?: (value: number) => string
  }>(),
  { hint: undefined, color: 'var(--primary)', limit: 5, format: (value: number) => fmt.int(value) },
)

const total = computed(() => props.items.reduce((sum, item) => sum + item.value, 0))
const peak = computed(() => Math.max(1, ...props.items.map((item) => item.value)))
const rows = computed(() => [...props.items].sort((a, b) => b.value - a.value).slice(0, props.limit))

function tipFor(row: BarListItem): string {
  const numbers = `${props.unit}: ${props.format(row.value)}, это ${fmt.pct(total.value ? row.value / total.value : 0)} от всех`
  return row.hint ? `${row.hint}. ${numbers}` : `${row.label}: ${numbers}`
}
</script>

<template>
  <div v-if="rows.length">
    <div class="label-caps mb-1.5"><span v-tip="props.hint" :class="props.hint && 'term'">{{ props.title }}</span></div>
    <div class="space-y-1">
      <div
        v-for="row in rows"
        :key="row.key"
        v-tip="tipFor(row)"
        class="relative flex items-center gap-2 overflow-hidden rounded-lg px-2 py-1 text-[12.5px]"
      >
        <span class="absolute inset-y-0 left-0 rounded-lg transition-[width] duration-700 ease-spring" :style="{ width: `${(row.value / peak) * 100}%`, background: props.color, opacity: 0.22 }" />
        <span class="relative min-w-0 flex-1 truncate text-muted-foreground"><span :class="row.hint && 'term'">{{ row.label }}</span></span>
        <span class="relative shrink-0 tabular-nums font-medium">{{ props.format(row.value) }}</span>
        <span class="relative w-11 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">{{ fmt.pct(total ? row.value / total : 0) }}</span>
      </div>
    </div>
  </div>
</template>
