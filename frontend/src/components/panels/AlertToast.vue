<script setup lang="ts">
import { Siren } from '@lucide/vue'
import { gsap } from 'gsap'
import { nextTick, ref, watch } from 'vue'
import { fmt } from '@/lib/format'
import { useLiveStore } from '@/stores/live'
import { useUiStore } from '@/stores/ui'

const live = useLiveStore()
const ui = useUiStore()
const box = ref<HTMLElement | null>(null)
const VISIBLE_SECONDS = 7

watch(
  () => live.toast,
  async (alert) => {
    if (!alert) return
    await nextTick()
    if (!box.value) return
    gsap
      .timeline({ onComplete: () => (live.toast = null) })
      .fromTo(box.value, { y: -40, scale: 0.6, opacity: 0, borderRadius: 999 }, { y: 0, scale: 1, opacity: 1, borderRadius: 26, duration: 0.7, ease: 'elastic.out(1, 0.7)' })
      .to(box.value, { y: -30, scale: 0.85, opacity: 0, duration: 0.35, ease: 'power2.in' }, `+=${VISIBLE_SECONDS}`)
  },
)

function open() {
  if (!live.toast) return
  ui.flyTarget = { lon: live.toast.lon, lat: live.toast.lat, zoom: 10 }
  live.toast = null
}
</script>

<template>
  <button v-if="live.toast" ref="box" type="button" class="panel flex items-center gap-3 px-4 py-3 text-left" role="alert" @click="open">
    <span class="grid size-10 shrink-0 place-items-center rounded-full bg-fire text-white"><Siren class="size-5" /></span>
    <span class="text-[13px] leading-snug">
      <span class="block font-semibold">{{ live.toast.n_hotspots }} новых термоточек: {{ live.toast.zone_name }}</span>
      <span class="text-muted-foreground">{{ fmt.dateTimeUtc(live.toast.acquired_at) }} · показать на карте</span>
    </span>
  </button>
</template>
