<script setup lang="ts">
import { ChevronRight } from '@lucide/vue'
import type { Component } from 'vue'

const props = defineProps<{ title: string; hint?: string; icon?: Component; color?: string; compact?: boolean }>()
const emit = defineEmits<{ open: [] }>()
</script>

<template>
  <button
    v-tip="props.hint"
    type="button"
    class="group block w-full rounded-[22px] bg-surface-2 px-4 py-3 text-left outline-none transition-[background-color,transform] duration-300 ease-spring hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-ring/60 active:scale-[0.985]"
    @click="emit('open')"
  >
    <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
      <component :is="props.icon" v-if="props.icon" class="size-3.5 shrink-0" :style="{ color: props.color }" />
      <span class="flex-1 truncate">{{ props.title }}</span>
      <span v-if="!props.compact" class="shrink-0 text-[11px] opacity-60 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100">Подробнее</span>
      <ChevronRight class="-mr-1 size-4 shrink-0 transition-transform duration-300 ease-spring group-hover:translate-x-0.5 group-hover:text-foreground" />
    </span>
    <span class="mt-1.5 block"><slot /></span>
  </button>
</template>
