<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ items: { label: string; value: number }[]; color?: string; height?: number }>(), {
  color: 'var(--primary)',
  height: 56,
})

const peak = computed(() => Math.max(1, ...props.items.map((i) => i.value)))
</script>

<template>
  <div class="flex items-end gap-[3px]" :style="{ height: `${props.height}px` }">
    <div
      v-for="item in props.items"
      :key="item.label"
      class="group relative min-w-[3px] flex-1 rounded-t-md rounded-b-[3px] transition-[height,opacity] duration-700 ease-spring hover:opacity-100"
      :class="item.value === peak ? 'opacity-100' : 'opacity-60'"
      :style="{ height: `${Math.max(4, (item.value / peak) * 100)}%`, background: props.color }"
      :title="`${item.label}: ${item.value.toLocaleString('ru-RU')}`"
    />
  </div>
</template>
