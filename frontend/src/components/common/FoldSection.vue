<script setup lang="ts">
import { ChevronDown } from '@lucide/vue'
import type { Component } from 'vue'

const props = defineProps<{ title: string; summary?: string; icon?: Component; open: boolean }>()
const emit = defineEmits<{ toggle: [] }>()
</script>

<template>
  <section class="rounded-[22px] transition-colors duration-300" :class="props.open ? 'bg-surface-2' : 'hover:bg-surface-2/60'">
    <button type="button" class="flex w-full items-center gap-2.5 px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/60 rounded-[22px]" :aria-expanded="props.open" @click="emit('toggle')">
      <component :is="props.icon" v-if="props.icon" class="size-4 shrink-0 text-primary" />
      <span class="text-[13px] font-medium">{{ props.title }}</span>
      <span v-if="!props.open && props.summary" class="min-w-0 flex-1 truncate text-right text-xs text-muted-foreground">{{ props.summary }}</span>
      <span v-else class="flex-1" />
      <ChevronDown class="size-4 shrink-0 text-muted-foreground transition-transform duration-500 ease-spring" :class="props.open && 'rotate-180'" />
    </button>
    <!--
      Свёрнутая секция схлопнута сеткой и погашена прозрачностью, но содержимое
      остаётся в дереве: Tab заходил внутрь и вёл на невидимые поля дат и чипы
      годов. Атрибут inert убирает свёрнутое из обхода и из дерева доступности,
      не ломая анимацию высоты.
    -->
    <div class="grid transition-[grid-template-rows] duration-500 ease-emphasized" :class="props.open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'">
      <div class="overflow-hidden">
        <div :inert="!props.open" class="px-4 pb-4 pt-0.5 transition-opacity duration-300" :class="props.open ? 'opacity-100' : 'opacity-0'"><slot /></div>
      </div>
    </div>
  </section>
</template>
