<script setup lang="ts">
import { ArrowUpRight, MapPinned } from '@lucide/vue'
import { computed } from 'vue'
import { type MapBounds, yandexMapsUrl } from '@/lib/yandex-maps'

const props = defineProps<{ bounds: MapBounds | null; place: string }>()
const href = computed(() => yandexMapsUrl(props.bounds))
</script>

<template>
  <div v-if="href">
    <a
      :href="href"
      target="_blank"
      rel="noopener noreferrer"
      :aria-label="`${place} — открыть в Яндекс Картах в новой вкладке`"
      class="group flex min-h-16 w-full items-center gap-3 rounded-[20px] border border-border/60 bg-surface-2 px-4 py-3 outline-none transition-colors duration-200 hover:border-primary/40 hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span class="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary-container text-on-primary-container"><MapPinned class="size-[18px]" aria-hidden="true" /></span>
      <span class="min-w-0 flex-1">
        <span class="block text-sm font-semibold">Яндекс Карты</span>
        <span class="mt-0.5 block truncate text-xs text-muted-foreground" :title="place">{{ place }}</span>
      </span>
      <ArrowUpRight class="size-[18px] shrink-0 text-muted-foreground transition-colors group-hover:text-primary" aria-hidden="true" />
    </a>
    <p class="mt-1.5 px-1 text-[11px] text-muted-foreground">Без слоя гари.</p>
  </div>
</template>
