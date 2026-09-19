<script setup lang="ts">
import { BarChart3, ChevronRight, History, LayoutDashboard, Maximize2, Minimize2, ShieldCheck, Sprout, Wind } from '@lucide/vue'
import { onKeyStroke } from '@vueuse/core'
import { gsap } from 'gsap'
import { type Component, computed, defineAsyncComponent, ref, watch } from 'vue'
import MorphLoader from '@/components/common/MorphLoader.vue'
import MorphPanel from '@/components/common/MorphPanel.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { fmt, plural } from '@/lib/format'
import { useQueryStore } from '@/stores/query'
import { type InsightView, useUiStore } from '@/stores/ui'
import ExportMenu from './ExportMenu.vue'

type DetailView = Exclude<InsightView, 'overview'>

const query = useQueryStore()
const ui = useUiStore()

const SECTIONS: { view: DetailView; title: string; icon: Component }[] = [
  { view: 'dynamics', title: 'Динамика и статистика', icon: BarChart3 },
  { view: 'emissions', title: 'Выбросы в атмосферу', icon: Wind },
  { view: 'profile', title: 'Профиль территории', icon: History },
  { view: 'restoration', title: 'Восстановление', icon: Sprout },
  { view: 'alarms', title: 'Ложные тревоги', icon: ShieldCheck },
]

/**
 * «Сводка» стоит первым пунктом списка слева, а не отдельной кнопкой «назад»
 * в противоположном от сворачивания углу. Список отвечает на «куда», кнопка
 * справа — на «насколько крупно»: два разных вопроса, два разных места.
 */
const NAV: { view: InsightView; title: string; icon: Component }[] = [
  { view: 'overview', title: 'Сводка', icon: LayoutDashboard },
  ...SECTIONS,
]
const VIEWS = {
  overview: defineAsyncComponent(() => import('./tabs/OverviewTab.vue')),
  dynamics: defineAsyncComponent(() => import('./tabs/DynamicsTab.vue')),
  emissions: defineAsyncComponent(() => import('./tabs/EmissionsTab.vue')),
  profile: defineAsyncComponent(() => import('./tabs/ProfileTab.vue')),
  restoration: defineAsyncComponent(() => import('./tabs/RestorationTab.vue')),
  alarms: defineAsyncComponent(() => import('./tabs/TechnogenicTab.vue')),
}
const COMPACT_CLASS = 'flex max-h-full w-[min(420px,100%)] flex-col'
const WIDE_CLASS = 'ml-auto flex h-full min-w-0 max-w-[1280px] flex-1 flex-col !bg-surface-1/95'

const content = ref<HTMLElement | null>(null)
const scroller = ref<HTMLElement | null>(null)
const isWide = computed(() => ui.insightTab !== 'overview')
const section = computed(() => SECTIONS.find((s) => s.view === ui.insightTab) ?? null)
const period = computed(() => [query.dateFrom, query.dateTo].map((d) => fmt.date(d).replace(/\s*г\.$/, '')).join(' - '))

/**
 * Одна кнопка в правом верхнем углу уменьшает панель на ступень: с разбора
 * во весь экран — до сводки, со сводки — до плитки. Раньше эти два действия
 * жили в противоположных углах, и чтобы выйти из разбора, приходилось тянуться
 * через весь экран влево.
 */
const shrinkTip = computed(() =>
  isWide.value ? 'Свернуть до сводки, клавиша Esc' : 'Скрыть панель, карта станет шире',
)
function shrink() {
  if (isWide.value) open('overview')
  else ui.insightOpen = false
}

function open(view: InsightView) {
  ui.insightTab = view
}

watch(
  () => ui.insightTab,
  (next, previous) => {
    scroller.value?.scrollTo({ top: 0 })
    if (!content.value) return
    const resized = next === 'overview' || previous === 'overview'
    gsap.from(content.value, { y: resized ? 0 : 14, opacity: 0, duration: resized ? 0.5 : 0.35, delay: resized ? 0.15 : 0, ease: 'power2.out', clearProps: 'all' })
  },
  { flush: 'post' },
)
// Перелёт к объекту происходит на карте, а широкий лист её закрывает.
watch(() => ui.flyTarget, (target) => target && isWide.value && open('overview'))
onKeyStroke('Escape', () => {
  if (isWide.value && ui.insightOpen && !ui.pipelineOpen && !ui.compareSceneId && !ui.passportTarget) open('overview')
})
</script>

<template>
  <MorphPanel :open="ui.insightOpen" :layout-key="isWide ? 'wide' : 'compact'" :class="isWide ? WIDE_CLASS : COMPACT_CLASS" pill-class="w-fit">
    <template #pill>
      <button v-tip="'Развернуть сводку по запросу'" type="button" class="flex h-12 items-center gap-2.5 pl-4 pr-5 text-sm font-medium" @click="ui.insightOpen = true">
        <LayoutDashboard class="size-4 text-primary" />
        <span v-if="query.report" class="tabular-nums">{{ fmt.ha(query.report.burn.total_ha) }} га</span>
        <span v-else>Сводка</span>
      </button>
    </template>

    <div class="flex min-h-0 flex-1 flex-col @container/panel">
    <header class="flex items-center gap-3 px-3 pt-3">
      <div class="min-w-0 flex-1 pl-2">
        <h2 class="truncate text-[15px] font-semibold leading-tight">{{ section?.title ?? 'Сводка' }}</h2>
        <p class="truncate text-[13px] text-muted-foreground">{{ query.regionName }}, {{ period }}</p>
      </div>
      <Button v-if="!isWide" v-tip="'Открыть подробную аналитику на весь экран'" variant="ghost" size="icon-sm" class="shrink-0" aria-label="Открыть подробную аналитику" @click="open('dynamics')"><Maximize2 /></Button>
      <Button
        v-tip="shrinkTip"
        variant="ghost"
        size="icon-sm"
        class="shrink-0"
        :aria-label="isWide ? 'Свернуть до сводки' : 'Скрыть панель'"
        @click="shrink"
      >
        <component :is="isWide ? Minimize2 : ChevronRight" />
      </Button>
    </header>

    <div class="flex min-h-0 flex-1">
      <nav v-if="isWide" class="hidden w-[236px] shrink-0 flex-col gap-1 py-3 pl-3 @3xl/panel:flex" aria-label="Разделы аналитики">
        <button
          v-for="item in NAV"
          :key="item.view"
          type="button"
          class="flex items-start gap-3 rounded-[20px] px-3.5 py-2.5 text-left outline-none transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-ring/60"
          :class="ui.insightTab === item.view ? 'bg-primary-container text-on-primary-container' : 'hover:bg-surface-2'"
          :aria-current="ui.insightTab === item.view ? 'page' : undefined"
          @click="open(item.view)"
        >
          <component :is="item.icon" class="mt-0.5 size-4 shrink-0" :class="ui.insightTab !== item.view && 'text-muted-foreground'" />
          <span class="min-w-0">
            <span class="block text-[13px] font-medium leading-tight">{{ item.title }}</span>
          </span>
        </button>
        <div v-if="query.report" class="mt-3 rounded-[20px] bg-surface-2 px-4 py-3">
          <div class="text-[13px] text-muted-foreground">Пройдено огнём</div>
          <div class="mt-0.5 flex items-baseline gap-1.5"><span class="display-number text-2xl">{{ fmt.ha(query.report.burn.total_ha) }}</span><span class="text-sm text-muted-foreground">га</span></div>
          <div class="mt-1 text-xs leading-snug text-muted-foreground">{{ plural(query.report.hotspots.fire_clusters, ['очаг', 'очага', 'очагов']) }}, отсеяно {{ fmt.int(query.report.hotspots.technogenic + query.report.hotspots.glint) }}</div>
        </div>
        <div class="mt-3 flex"><ExportMenu /></div>
      </nav>

      <div ref="scroller" class="thin-scroll relative min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-4 pb-3 pt-3 @container">
        <div v-if="query.error" class="rounded-2xl bg-destructive/15 px-4 py-3 text-sm text-destructive">{{ query.error }}</div>
        <div v-else-if="!query.report" class="space-y-3">
          <Skeleton class="h-36 rounded-[24px]" />
          <div class="grid grid-cols-2 gap-2"><Skeleton v-for="i in 2" :key="i" class="h-20 rounded-[22px]" /></div>
          <Skeleton class="h-20 rounded-[22px]" />
          <Skeleton class="h-20 rounded-[22px]" />
        </div>
        <div v-else ref="content" :class="{ 'opacity-60 transition-opacity': query.loading }">
          <component :is="VIEWS[ui.insightTab]" :report="query.report" @open="open" />
        </div>
        <Transition enter-active-class="transition duration-300" enter-from-class="opacity-0 scale-75" leave-active-class="transition duration-200" leave-to-class="opacity-0 scale-75">
          <div v-if="query.loading && query.report" class="pointer-events-none absolute right-5 top-4"><MorphLoader :size="28" /></div>
        </Transition>
      </div>
    </div>

    <footer class="flex items-center gap-2 border-t border-border/60 px-4 py-3" :class="isWide && '@3xl/panel:hidden'">
      <ExportMenu />
    </footer>
    </div>
  </MorphPanel>
</template>
