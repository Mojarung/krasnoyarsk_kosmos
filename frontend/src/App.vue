<script setup lang="ts">
import { gsap } from 'gsap'
import { useEventListener } from '@vueuse/core'
import { defineAsyncComponent, nextTick, onMounted, ref, watch } from 'vue'
import MorphLoader from '@/components/common/MorphLoader.vue'
import AlertToast from '@/components/panels/AlertToast.vue'
import InsightPanel from '@/components/panels/InsightPanel.vue'
import QueryPanel from '@/components/panels/QueryPanel.vue'
import TimelineBar from '@/components/panels/TimelineBar.vue'
import TopBar from '@/components/panels/TopBar.vue'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'
import { APP_NAME } from '@/lib/brand'
import { useUiStore } from '@/stores/ui'
import { useInspectionStore } from '@/stores/inspection'
import { useSpatialStore } from '@/stores/spatial'
import SpatialPanel from '@/components/panels/SpatialPanel.vue'

const MapView = defineAsyncComponent(() => import('@/components/map/MapView.vue'))
const PipelineDrawer = defineAsyncComponent(() => import('@/components/panels/PipelineDrawer.vue'))
const SceneCompare = defineAsyncComponent(() => import('@/components/panels/SceneCompare.vue'))
const FirePassport = defineAsyncComponent(() => import('@/components/panels/FirePassport.vue'))
const VegetationHistory = defineAsyncComponent(() => import('@/components/panels/VegetationHistory.vue'))
const InspectionPlanner = defineAsyncComponent(() => import('@/components/panels/InspectionPlanner.vue'))
const SharedInspection = defineAsyncComponent(() => import('@/components/panels/SharedInspection.vue'))
const sharedToken = ref(new URLSearchParams(window.location.hash.slice(1)).get('inspection'))
useEventListener(window, 'hashchange', () => {
  sharedToken.value = new URLSearchParams(window.location.hash.slice(1)).get('inspection')
})

const query = useQueryStore()
const live = useLiveStore()
const ui = useUiStore()
const inspection = useInspectionStore()
const spatial = useSpatialStore()
watch(() => ui.passportTarget, () => spatial.close())
watch(() => query.params, () => spatial.close())

const mapReady = ref(false)
const booted = ref(false)
const bootError = ref<string | null>(null)
const splash = ref<HTMLElement | null>(null)
const chrome = ref<HTMLElement | null>(null)
const mapView = ref<{ setSceneQuicklook: (name: string) => void } | null>(null)
const pipelineMounted = ref(false)

async function boot() {
  if (sharedToken.value) return
  bootError.value = null
  try {
    await query.bootstrap()
    live.connect()
    void live.loadJobs()
    void live.loadZones()
    booted.value = true
  } catch {
    bootError.value = 'API не отвечает. Проверьте, что сервис запущен: docker compose up'
  }
}

watch([mapReady, booted], async ([map, data]) => {
  if (!map || !data) return
  await nextTick()
  const timeline = gsap.timeline()
  if (splash.value) timeline.to(splash.value, { opacity: 0, scale: 1.06, duration: 0.7, ease: 'power2.inOut', onComplete: () => splash.value?.remove() })
  if (chrome.value) {
    timeline.from(
      chrome.value.querySelectorAll('[data-enter]'),
      { opacity: 0, y: 26, scale: 0.94, duration: 0.9, ease: 'elastic.out(1, 0.8)', stagger: 0.09, clearProps: 'all' },
      '-=0.35',
    )
  }
})
watch(() => ui.pipelineOpen, (open) => open && (pipelineMounted.value = true))
watch(() => query.params, () => { ui.vegetationEvent = null })

/*
 * Карточка «до/после» шириной 720 px ложилась поверх сводки и резала главное
 * число. Шкала времени при сравнении уже уезжает — обе панели сворачиваются в
 * плитку по тому же поводу и возвращаются, когда карточку закрыли.
 */
let panelsWereOpen: [boolean, boolean] = [true, true]
watch(
  () => ui.compareSceneId,
  (id, previous) => {
    if (id && !previous) {
      panelsWereOpen = [ui.insightOpen, ui.queryOpen]
      ui.insightOpen = false
      ui.queryOpen = false
    } else if (!id && previous) {
      ;[ui.insightOpen, ui.queryOpen] = panelsWereOpen
    }
  },
)

onMounted(boot)
watch(sharedToken, (token) => {
  mapReady.value = false
  booted.value = false
  inspection.close()
  if (!token) void boot()
})
</script>

<template>
  <SharedInspection v-if="sharedToken" :key="sharedToken" :token="sharedToken" />
  <main v-else class="relative h-full overflow-hidden bg-background">
    <MapView ref="mapView" @ready="mapReady = true" />

    <div ref="chrome" class="pointer-events-none absolute inset-0 flex flex-col gap-3 p-3 sm:p-4">
      <TopBar data-enter />

      <!--
        Ниже 1024 px обе панели раньше просто исчезали (max-lg:hidden) и заменить
        их было нечем: на планшете и телефоне оставалась голая карта без запроса
        и без сводки. Теперь они стартуют свёрнутыми в плитку, стопкой, и
        раскрываются во всю доступную ширину — карта при этом остаётся видна.
      -->
      <div v-show="!ui.passportTarget" class="flex min-h-0 flex-1 items-start justify-between gap-3 max-lg:flex-col max-lg:justify-start">
        <QueryPanel data-enter class="pointer-events-auto shrink-0 max-lg:max-w-full" />
        <InsightPanel data-enter class="pointer-events-auto max-lg:max-w-full" />
      </div>

      <!-- Плашка копирайта карты сидит в правом нижнем углу и на узком экране
           накрывала подписи годов: отводим шкале запас снизу. -->
      <div v-show="!ui.passportTarget" class="flex justify-center max-sm:pb-6">
        <TimelineBar data-enter class="pointer-events-auto transition-[opacity,transform] duration-300" :class="ui.compareSceneId && '!pointer-events-none translate-y-6 !opacity-0'" />
      </div>
    </div>

    <div v-if="ui.passportTarget" v-show="!ui.compareSceneId" class="pointer-events-none absolute bottom-8 right-3 top-20 z-10 flex justify-end sm:right-4 max-sm:bottom-7 max-sm:left-3 max-sm:top-[30dvh]">
      <FirePassport v-show="!inspection.event && !ui.vegetationEvent && !spatial.mode" class="pointer-events-auto" />
    </div>

    <SpatialPanel v-if="spatial.mode" />
    <div v-if="ui.vegetationEvent" class="pointer-events-none absolute inset-x-3 bottom-5 top-20 z-30 flex justify-end sm:right-4">
      <VegetationHistory :key="ui.vegetationEvent.id" :event="ui.vegetationEvent" class="pointer-events-auto" />
    </div>

    <div v-if="inspection.event" v-show="!inspection.picking" class="pointer-events-none absolute bottom-8 right-3 top-20 z-20 flex items-start justify-end sm:right-4 max-sm:bottom-7 max-sm:left-3 max-sm:top-[42dvh]">
      <InspectionPlanner class="pointer-events-auto" />
    </div>
    <div v-if="inspection.picking" class="pointer-events-none absolute inset-x-3 bottom-8 z-30 flex justify-center">
      <div class="panel pointer-events-auto max-w-md px-5 py-4">
        <p class="text-sm font-semibold">{{ inspection.picking === 'site' ? '1 · Нажмите на участок гари' : '2 · Выберите место остановки' }}</p>
        <button class="mt-3 rounded-full bg-secondary px-4 py-2 text-xs focus-visible:ring-2 focus-visible:ring-ring" @click="inspection.picking = null">Отменить выбор точки</button>
      </div>
    </div>

    <div class="pointer-events-none absolute inset-x-0 bottom-4 z-10 flex justify-center">
      <Transition
        enter-active-class="transition-[opacity,transform] duration-500 ease-spring"
        enter-from-class="opacity-0 translate-y-8 scale-90"
        leave-active-class="transition-[opacity,transform] duration-200"
        leave-to-class="opacity-0 translate-y-6 scale-95"
      >
        <SceneCompare v-if="ui.compareSceneId" class="pointer-events-auto" @quicklook="(name) => mapView?.setSceneQuicklook(name)" />
      </Transition>
    </div>

    <!--
      Подсказка по рисованию жила только в боковой панели, а в этот момент
      пользователь смотрит на карту. Интуитивная попытка протянуть мышью вместо
      двух кликов панорамирует карту и уносит её с территории.
    -->
    <Transition
      enter-active-class="transition-[opacity,transform] duration-300 ease-spring"
      enter-from-class="opacity-0 -translate-y-2"
      leave-active-class="transition-opacity duration-200"
      leave-to-class="opacity-0"
    >
      <div v-if="ui.drawMode !== 'idle'" class="pointer-events-none absolute inset-x-0 top-20 z-30 flex justify-center">
        <p class="panel !rounded-full px-5 py-2 text-[13px] font-medium">
          {{ ui.drawMode === 'rectangle' ? 'Кликните два противоположных угла' : 'Ставьте вершины кликами, замкните на первой' }}
        </p>
      </div>
    </Transition>

    <div class="pointer-events-none absolute inset-x-0 top-20 z-30 flex justify-center"><AlertToast class="pointer-events-auto" /></div>
    <PipelineDrawer v-if="pipelineMounted" />

    <div ref="splash" class="absolute inset-0 z-50 grid place-items-center bg-background">
      <div class="flex flex-col items-center gap-5 text-center">
        <MorphLoader :size="84" />
        <div>
          <div class="display-number text-3xl">{{ APP_NAME }}</div>
          <p class="mt-2 max-w-72 text-sm text-muted-foreground">{{ bootError ?? 'Поднимаем карту, термоточки и контуры гарей' }}</p>
        </div>
        <button v-if="bootError" type="button" class="rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-foreground" @click="boot">Повторить</button>
      </div>
    </div>
  </main>
</template>
