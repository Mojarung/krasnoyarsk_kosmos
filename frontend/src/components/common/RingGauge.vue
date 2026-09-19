<script setup lang="ts">
import { computed } from 'vue'
import { fmt } from '@/lib/format'

const props = withDefaults(defineProps<{ value: number | null; label: string; size?: number; color?: string }>(), {
  size: 76,
  color: 'var(--primary)',
})

const RADIUS = 42
const LENGTH = 2 * Math.PI * RADIUS
const offset = computed(() => LENGTH * (1 - Math.min(Math.max(props.value ?? 0, 0), 1)))
</script>

<template>
  <div class="flex flex-col items-center gap-1.5">
    <div class="relative" :style="{ width: `${props.size}px`, height: `${props.size}px` }">
      <svg viewBox="0 0 100 100" class="-rotate-90">
        <circle cx="50" cy="50" :r="RADIUS" fill="none" stroke="var(--surface-3)" stroke-width="9" />
        <circle
          cx="50"
          cy="50"
          :r="RADIUS"
          fill="none"
          :stroke="props.color"
          stroke-width="9"
          stroke-linecap="round"
          :stroke-dasharray="LENGTH"
          :stroke-dashoffset="offset"
          class="transition-[stroke-dashoffset] duration-1000 ease-emphasized"
        />
      </svg>
      <span class="absolute inset-0 grid place-items-center text-[15px] font-semibold tabular-nums">
        {{ fmt.ratio(props.value) }}
      </span>
    </div>
    <span class="text-center text-[11px] leading-tight text-muted-foreground">{{ props.label }}</span>
  </div>
</template>
