<script setup lang="ts">
export interface StatRow {
  label: string
  value: string
  hint?: string
}

const props = defineProps<{ title: string; rows: StatRow[]; hint?: string }>()
</script>

<template>
  <div>
    <div class="mb-1.5 text-[13px] text-muted-foreground">
      <span v-tip="props.hint" :class="props.hint && 'term'">{{ props.title }}</span>
    </div>
    <div class="divide-y divide-border/50">
      <div v-for="row in props.rows" :key="row.label" v-tip="row.hint" class="flex items-baseline justify-between gap-3 py-2 text-[14px]">
        <span class="text-muted-foreground" :class="row.hint && 'term'">{{ row.label }}</span>
        <span class="shrink-0 font-medium tabular-nums">{{ row.value }}</span>
      </div>
    </div>
  </div>
</template>
