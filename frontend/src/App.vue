<script setup lang="ts">
import { gsap } from 'gsap'
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

const MapView = defineAsyncComponent(() => import('@/components/map/MapView.vue'))
const PipelineDrawer = defineAsyncComponent(() => import('@/components/panels/PipelineDrawer.vue'))
const SceneCompare = defineAsyncComponent(() => import('@/components/panels/SceneCompare.vue'))

const query = useQueryStore()
const live = useLiveStore()
const ui = useUiStore()

const mapReady = ref(false)
const booted = ref(false)
const bootError = ref<string | null>(null)
const splash = ref<HTMLElement | null>(null)
const chrome = ref<HTMLElement | null>(null)
const mapView = ref<{ setSceneQuicklook: (name: string) => void } | null>(null)
const pipelineMounted = ref(false)

async function boot() {
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
    timeline.fromTo(
      chrome.value.querySelectorAll('[data-enter]'),
      { opacity: 0, y: 26, scale: 0.94 },
      { opacity: 1, y: 0, scale: 1, duration: 0.9, ease: 'elastic.out(1, 0.8)', stagger: 0.09, clearProps: 'transform' },
      '-=0.35',
    )
  }
})
watch(() => ui.pipelineOpen, (open) => open && (pipelineMounted.value = true))

onMounted(boot)
</script>

<template>
  <main class="relative h-full overflow-hidden bg-background">
    <MapView ref="mapView" @ready="mapReady = true" />

    <div ref="chrome" class="pointer-events-none absolute inset-0 flex flex-col gap-3 p-3 sm:p-4">
      <TopBar data-enter class="opacity-0" />

      <div class="flex min-h-0 flex-1 items-start justify-between gap-3">
        <QueryPanel data-enter class="pointer-events-auto opacity-0 max-lg:hidden" />
        <InsightPanel data-enter class="pointer-events-auto opacity-0 max-lg:hidden" />
      </div>

      <div class="flex justify-center">
        <TimelineBar data-enter class="pointer-events-auto opacity-0 transition-[opacity,transform] duration-300" :class="ui.compareSceneId && '!pointer-events-none translate-y-6 !opacity-0'" />
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
