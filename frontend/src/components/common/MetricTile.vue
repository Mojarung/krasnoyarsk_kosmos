<script setup lang="ts">
import type { Component } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{
  label: string
  value: string
  unit?: string
  hint?: string
  icon?: Component
  tone?: 'default' | 'fire' | 'technogenic' | 'tertiary'
}>()

const TONES = {
  default: 'bg-surface-2',
  fire: 'bg-primary-container text-on-primary-container',
  technogenic: 'bg-technogenic/15',
  tertiary: 'bg-tertiary-container/60',
}
</script>

<template>
  <div
    :class="cn('group rounded-[20px] px-3.5 py-3 transition-[border-radius,transform] duration-500 ease-spring hover:rounded-[28px] hover:-translate-y-0.5', TONES[props.tone ?? 'default'])"
    :title="props.hint"
  >
    <div class="flex items-center gap-1.5 text-[11px] leading-tight opacity-75">
      <component :is="props.icon" v-if="props.icon" class="size-3.5 shrink-0" />
      <span class="truncate">{{ props.label }}</span>
    </div>
    <div class="mt-1.5 flex items-baseline gap-1">
      <span class="text-xl font-semibold leading-none tabular-nums">{{ props.value }}</span>
      <span v-if="props.unit" class="text-xs opacity-70">{{ props.unit }}</span>
    </div>
  </div>
</template>
