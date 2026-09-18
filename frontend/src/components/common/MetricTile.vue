<script setup lang="ts">
import type { Component } from 'vue'

const props = defineProps<{ label: string; value: string; unit?: string; sub?: string; hint?: string; icon?: Component; color?: string }>()
</script>

<template>
  <div v-tip="props.hint" class="rounded-[20px] bg-surface-2 px-3.5 py-3 transition-[border-radius] duration-500 ease-spring hover:rounded-[28px]">
    <div class="flex items-center gap-1.5 text-[11px] leading-tight text-muted-foreground">
      <component :is="props.icon" v-if="props.icon" class="size-3.5 shrink-0" :style="{ color: props.color }" />
      <span class="truncate">{{ props.label }}</span>
    </div>
    <div class="mt-1.5 flex items-baseline gap-1">
      <span class="text-xl font-semibold leading-none tabular-nums">{{ props.value }}</span>
      <span v-if="props.unit" class="text-xs text-muted-foreground">{{ props.unit }}</span>
    </div>
    <div v-if="props.sub" class="mt-1 truncate text-[11px] text-muted-foreground">{{ props.sub }}</div>
  </div>
</template>
