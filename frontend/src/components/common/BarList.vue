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

/**
 * Доля от всех живёт в подсказке, а не в третьей колонке: полоса уже кодирует
 * величину, число её называет — процент был третьим изображением одного и того же.
 */
function tipFor(row: BarListItem): string {
  const numbers = `${props.format(row.value)} ${props.unit}, это ${fmt.pct(total.value ? row.value / total.value : 0)} от всех`
  return row.hint ? `${row.hint}. ${numbers}` : `${row.label}: ${numbers}`
}
</script>

<template>
  <figure v-if="rows.length">
    <figcaption class="mb-2 text-[13px] text-muted-foreground">
      <span v-tip="props.hint" :class="props.hint && 'term'">{{ props.title }}</span>
    </figcaption>
    <div class="space-y-2.5">
      <div v-for="row in rows" :key="row.key" v-tip="tipFor(row)">
        <div class="flex items-baseline gap-3 text-[14px]">
          <span class="min-w-0 flex-1 truncate"><span :class="row.hint && 'term'">{{ row.label }}</span></span>
          <span class="shrink-0 font-medium tabular-nums">{{ props.format(row.value) }}</span>
        </div>
        <div class="mt-1 h-1 rounded-full bg-surface-3">
          <div
            class="h-full rounded-full transition-[width] duration-700 ease-spring"
            :style="{ width: `${Math.max(2, (row.value / peak) * 100)}%`, background: props.color }"
          />
        </div>
      </div>
    </div>
  </figure>
</template>
