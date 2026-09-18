<script setup lang="ts">
import { computed } from 'vue'
import { fmt } from '@/lib/format'
import type { SeverityShare } from '@/lib/types'

const props = defineProps<{ items: SeverityShare[] }>()

const COLORS = { 1: 'var(--sev-1)', 2: 'var(--sev-2)', 3: 'var(--sev-3)' } as const
const total = computed(() => props.items.reduce((sum, item) => sum + item.area_ha, 0))
</script>

<template>
  <div>
    <div class="flex h-3.5 gap-0.5 overflow-hidden rounded-full bg-surface-3">
      <div
        v-for="item in props.items"
        :key="item.severity"
        class="h-full rounded-full transition-[flex-grow] duration-700 ease-spring"
        :style="{ flexGrow: total ? Math.max(item.share, 0.004) : 0, flexBasis: 0, background: COLORS[item.severity] }"
      />
    </div>
    <div class="mt-3 grid grid-cols-3 gap-2">
      <div v-for="item in props.items" :key="item.severity" class="rounded-2xl bg-surface-2 px-3 py-2.5">
        <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span class="size-2 rounded-full" :style="{ background: COLORS[item.severity] }" />
          {{ item.label }}
        </div>
        <div class="mt-1 text-lg font-semibold leading-none tabular-nums">{{ fmt.ha(item.area_ha) }}<span class="ml-1 text-xs font-normal text-muted-foreground">га</span></div>
        <div class="mt-1 text-xs text-muted-foreground tabular-nums">{{ fmt.pct(item.share) }}</div>
      </div>
    </div>
  </div>
</template>
