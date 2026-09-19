<script setup lang="ts">
import { Pause, Play, RotateCcw } from '@lucide/vue'
import { gsap } from 'gsap'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { DAY_MS, fmt, toIsoDate } from '@/lib/format'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'

const query = useQueryStore()
const ui = useUiStore()

const PLAY_SECONDS_PER_YEAR = 7
const MIN_PLAY_SECONDS = 8
const MAX_PLAY_SECONDS = 40

interface Bin {
  key: string
  start: number
  end: number
  fire: number
  filtered: number
  burnHa: number
}

const track = ref<HTMLElement | null>(null)
const drag = ref<{ from: number; to: number } | null>(null)
let tween: gsap.core.Tween | null = null

const bins = computed<Bin[]>(() => {
  const data = query.meta?.data
  if (!data?.date_min || !data.date_max) return []
  const result: Bin[] = []
  const cursor = new Date(`${data.date_min.slice(0, 7)}-01T00:00:00Z`)
  const last = Date.parse(data.date_max)
  while (cursor.getTime() <= last) {
    const start = cursor.getTime()
    cursor.setUTCMonth(cursor.getUTCMonth() + 1)
    result.push({ key: toIsoDate(start).slice(0, 7), start, end: cursor.getTime() - DAY_MS, fire: 0, filtered: 0, burnHa: 0 })
  }
  const index = new Map(result.map((b) => [b.key, b]))
  for (const day of query.timeline) {
    const bin = index.get(day.day.slice(0, 7))
    if (!bin) continue
    bin.fire += day.fire
    bin.filtered += day.filtered
    bin.burnHa += day.burn_ha
  }
  return result
})
const peakFire = computed(() => Math.max(1, ...bins.value.map((b) => b.fire + b.filtered)))
const years = computed(() => bins.value.filter((b) => b.key.endsWith('-01') || b === bins.value[0]).map((b) => ({ key: b.key, label: b.key.slice(0, 4), index: bins.value.indexOf(b) })))

const fromMs = computed(() => Date.parse(query.dateFrom))
const toMs = computed(() => Date.parse(query.dateTo))
const selection = computed(() => drag.value ?? { from: bins.value.findIndex((b) => b.end >= fromMs.value), to: findLastIndex(bins.value, (b) => b.start <= toMs.value) })
const playheadLabel = computed(() => (ui.playhead == null ? null : fmt.dayMonth(ui.playhead * 1000) + ' ' + new Date(ui.playhead * 1000).getUTCFullYear()))
const playheadPercent = computed(() => {
  if (ui.playhead == null || !bins.value.length) return null
  const first = bins.value[0].start
  const span = bins.value[bins.value.length - 1].end + DAY_MS - first
  return ((ui.playhead * 1000 - first) / span) * 100
})

function findLastIndex<T>(items: T[], predicate: (item: T) => boolean): number {
  for (let i = items.length - 1; i >= 0; i--) if (predicate(items[i])) return i
  return -1
}

function isSelected(index: number): boolean {
  const low = Math.min(selection.value.from, selection.value.to)
  const high = Math.max(selection.value.from, selection.value.to)
  return index >= low && index <= high
}

function binAt(event: PointerEvent): number {
  const rect = track.value!.getBoundingClientRect()
  const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 0.9999)
  return Math.floor(ratio * bins.value.length)
}

function onPointerDown(event: PointerEvent) {
  if (!bins.value.length) return
  stop()
  track.value!.setPointerCapture(event.pointerId)
  const index = binAt(event)
  drag.value = { from: index, to: index }
}

function onPointerMove(event: PointerEvent) {
  if (drag.value) drag.value = { from: drag.value.from, to: binAt(event) }
}

function onPointerUp() {
  if (!drag.value) return
  const low = bins.value[Math.min(drag.value.from, drag.value.to)]
  const high = bins.value[Math.max(drag.value.from, drag.value.to)]
  drag.value = null
  const max = query.meta?.data.date_max
  const end = toIsoDate(high.end)
  query.setPeriod(toIsoDate(low.start), max && end > max ? max : end)
}

function stop() {
  tween?.kill()
  tween = null
  ui.playing = false
  ui.playhead = null
}

function play() {
  if (ui.playing) {
    tween?.pause()
    ui.playing = false
    return
  }
  if (tween) {
    tween.resume()
    ui.playing = true
    return
  }
  const start = fromMs.value / 1000
  const end = toMs.value / 1000 + 86_400
  const years = (end - start) / (365 * 86_400)
  const state = { ts: start }
  ui.playing = true
  ui.playhead = start
  tween = gsap.to(state, {
    ts: end,
    duration: Math.min(Math.max(years * PLAY_SECONDS_PER_YEAR, MIN_PLAY_SECONDS), MAX_PLAY_SECONDS),
    ease: 'none',
    onUpdate: () => {
      const day = Math.floor(state.ts / 86_400) * 86_400
      if (day !== ui.playhead) ui.playhead = day
    },
    onComplete: () => {
      tween = null
      ui.playing = false
    },
  })
}

watch([() => query.dateFrom, () => query.dateTo], stop)
onBeforeUnmount(stop)
</script>

<template>
  <section class="panel flex w-full max-w-[860px] items-center gap-3 px-3 py-2.5" aria-label="Шкала времени">
    <div class="flex shrink-0 items-center gap-1">
      <Button v-tip="ui.playing ? 'Пауза' : 'Проиграть выбранный период: термоточки вспыхивают по дням, гари проявляются по дате снимка'" size="icon-lg" :variant="ui.playing ? 'tonal' : 'default'" :aria-label="ui.playing ? 'Пауза' : 'Проиграть период'" @click="play">
        <component :is="ui.playing ? Pause : Play" class="!size-5" />
      </Button>
      <Button v-if="ui.playhead != null" v-tip="'Остановить и показать весь период'" size="icon-sm" variant="ghost" aria-label="Сбросить проигрывание" @click="stop"><RotateCcw /></Button>
    </div>

    <div class="min-w-0 flex-1">
      <div class="mb-1 flex items-center justify-between text-[13px] text-muted-foreground">
        <!-- На узком экране подсказка ломалась в три строки рядом с легендой:
             легенда важнее, она объясняет цвет столбиков. -->
        <span v-if="playheadLabel" class="font-medium text-primary tabular-nums">{{ playheadLabel }}</span>
        <span v-else class="truncate max-sm:hidden">Потяните по шкале, чтобы выбрать период</span>
        <span class="flex shrink-0 items-center gap-3">
          <span class="flex items-center gap-1"><i class="size-1.5 rounded-full bg-fire" />термоточки</span>
          <span class="flex items-center gap-1"><i class="size-1.5 rounded-full bg-technogenic" />отсеяно</span>
        </span>
      </div>

      <div
        ref="track"
        class="relative flex h-12 cursor-col-resize touch-none items-end gap-px select-none"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <div
          v-for="(bin, index) in bins"
          :key="bin.key"
          class="relative flex h-full flex-1 flex-col justify-end rounded-[5px] transition-colors duration-300"
          :class="isSelected(index) ? 'bg-primary/12' : 'bg-transparent'"
          :title="`${bin.key}: ${bin.fire} термоточек, ${bin.filtered} отсеяно, ${Math.round(bin.burnHa)} га`"
        >
          <span class="w-full rounded-t-[3px] bg-technogenic transition-[height,opacity] duration-500 ease-spring" :class="isSelected(index) ? 'opacity-80' : 'opacity-25'" :style="{ height: `${(bin.filtered / peakFire) * 100}%` }" />
          <span class="w-full bg-fire transition-[height,opacity] duration-500 ease-spring" :class="[isSelected(index) ? 'opacity-100' : 'opacity-30', bin.filtered ? '' : 'rounded-t-[3px]']" :style="{ height: `${(bin.fire / peakFire) * 100}%` }" />
        </div>
        <div v-if="playheadPercent != null" class="pointer-events-none absolute inset-y-0 w-0.5 rounded-full bg-primary shadow-[0_0_12px_var(--primary)]" :style="{ left: `${playheadPercent}%` }" />
      </div>

      <div class="relative mt-1.5 h-4 text-[13px] text-muted-foreground">
        <span v-for="year in years" :key="year.key" class="absolute" :style="{ left: `${(year.index / bins.length) * 100}%` }">{{ year.label }}</span>
      </div>
    </div>
  </section>
</template>
