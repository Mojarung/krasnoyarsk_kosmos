<script setup lang="ts">
import { BarChart3, ChevronRight, Factory, FileText, Sprout } from '@lucide/vue'
import { gsap } from 'gsap'
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import MorphLoader from '@/components/common/MorphLoader.vue'
import MorphPanel from '@/components/common/MorphPanel.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { fmt } from '@/lib/format'
import { useQueryStore } from '@/stores/query'
import { type InsightTab, useUiStore } from '@/stores/ui'

const query = useQueryStore()
const ui = useUiStore()

const TABS: { value: InsightTab; label: string; icon: typeof FileText; hint: string }[] = [
  { value: 'report', label: 'Справка', icon: FileText, hint: 'Площадь гари, степени поражения, очаги и выгрузка' },
  { value: 'metrics', label: 'Метрики', icon: BarChart3, hint: 'Качество моделей на эталоне и статистика термоточек' },
  { value: 'restoration', label: 'Лес', icon: Sprout, hint: 'План лесовосстановления и оценка затрат' },
  { value: 'technogenic', label: 'Фильтр', icon: Factory, hint: 'Что отсеяно как техногенное и почему' },
]
const VIEWS = {
  report: defineAsyncComponent(() => import('./tabs/ReportTab.vue')),
  metrics: defineAsyncComponent(() => import('./tabs/MetricsTab.vue')),
  restoration: defineAsyncComponent(() => import('./tabs/RestorationTab.vue')),
  technogenic: defineAsyncComponent(() => import('./tabs/TechnogenicTab.vue')),
}
const ORDER = TABS.map((t) => t.value)

const content = ref<HTMLElement | null>(null)
const view = computed(() => VIEWS[ui.insightTab])

watch(
  () => ui.insightTab,
  (next, previous) => {
    if (!content.value) return
    const direction = ORDER.indexOf(next) > ORDER.indexOf(previous) ? 1 : -1
    gsap.fromTo(content.value, { x: 26 * direction, opacity: 0 }, { x: 0, opacity: 1, duration: 0.45, ease: 'expo.out', clearProps: 'transform' })
  },
  { flush: 'post' },
)
</script>

<template>
  <MorphPanel :open="ui.insightOpen" class="flex max-h-full w-[420px] flex-col" pill-class="w-fit">
    <template #pill>
      <button v-tip="'Развернуть аналитику'" type="button" class="flex h-12 items-center gap-2.5 pl-4 pr-5 text-sm font-medium" @click="ui.insightOpen = true">
        <FileText class="size-4 text-primary" />
        <span v-if="query.report" class="tabular-nums">{{ fmt.ha(query.report.burn.total_ha) }} га</span>
        <span v-else>Аналитика</span>
      </button>
    </template>

    <header class="flex items-center gap-2 px-4 pt-4">
      <BubbleTabs v-model="ui.insightTab" :options="TABS" size="sm" stretch />
      <Button v-tip="'Свернуть панель, карта станет шире'" variant="ghost" size="icon-sm" aria-label="Свернуть аналитику" @click="ui.insightOpen = false"><ChevronRight /></Button>
    </header>

    <div class="flex items-center justify-between px-5 pt-3 text-xs text-muted-foreground">
      <span class="truncate">{{ query.regionName }}</span>
      <span class="shrink-0 tabular-nums">{{ fmt.date(query.dateFrom) }} - {{ fmt.date(query.dateTo) }}</span>
    </div>

    <div class="thin-scroll relative flex-1 overflow-y-auto overflow-x-hidden px-4 pb-4 pt-3">
      <div v-if="query.error" class="rounded-2xl bg-destructive/15 px-4 py-3 text-sm text-destructive">{{ query.error }}</div>
      <div v-else-if="!query.report" class="space-y-3">
        <Skeleton class="h-28 rounded-[24px]" />
        <Skeleton class="h-4 rounded-full" />
        <div class="grid grid-cols-2 gap-2"><Skeleton v-for="i in 4" :key="i" class="h-16 rounded-[20px]" /></div>
      </div>
      <div v-else ref="content" :class="{ 'opacity-60 transition-opacity': query.loading }">
        <component :is="view" :report="query.report" />
      </div>
      <Transition enter-active-class="transition duration-300" enter-from-class="opacity-0 scale-75" leave-active-class="transition duration-200" leave-to-class="opacity-0 scale-75">
        <div v-if="query.loading && query.report" class="pointer-events-none absolute right-5 top-4"><MorphLoader :size="28" /></div>
      </Transition>
    </div>
  </MorphPanel>
</template>
