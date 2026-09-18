<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ values: number[]; color?: string; height?: number }>(), { color: 'var(--primary)', height: 30 })
const peak = computed(() => Math.max(0, ...props.values))
</script>

<template>
  <span class="flex items-end gap-px" :style="{ height: `${props.height}px` }" aria-hidden="true">
    <span
      v-for="(value, index) in props.values"
      :key="index"
      class="min-w-px flex-1 rounded-t-[2px] transition-[height] duration-700 ease-spring"
      :style="{
        height: peak > 0 && value > 0 ? `${Math.max(8, (value / peak) * 100)}%` : '2px',
        background: value > 0 ? props.color : 'var(--border)',
        opacity: value === peak ? 1 : 0.65,
      }"
    />
  </span>
</template>
