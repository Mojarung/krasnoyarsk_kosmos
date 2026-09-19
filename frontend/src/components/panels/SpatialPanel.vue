<script setup lang="ts">
import { onKeyStroke } from '@vueuse/core'
import { X, ChevronRight, ChevronsLeftRight } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import MorphLoader from '@/components/common/MorphLoader.vue'
import { useSpatialStore } from '@/stores/spatial'
import { fmt } from '@/lib/format'
import { WORK_COLORS } from '@/lib/work-map'
const spatial = useSpatialStore()
onKeyStroke('Escape', e => { if (spatial.mode) { e.preventDefault(); spatial.close() } })
function drag(e: PointerEvent) {
  if (e.type === 'pointerdown') (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  if (e.type === 'pointermove' && e.buttons === 0 && e.pointerType !== 'touch') return
  if (e.type === 'pointermove' && !(e.currentTarget as HTMLElement).hasPointerCapture(e.pointerId)) return
  spatial.split = Math.max(5, Math.min(95, e.clientX / window.innerWidth * 100))
}
</script>

<template>
  <div class="pointer-events-none absolute inset-0 z-20" :aria-label="spatial.mode === 'works' ? 'Участки работ на карте' : 'Сравнение на карте'">
    <div class="absolute left-3 right-3 top-20 flex items-start justify-between gap-2 sm:left-4 sm:right-4">
      <div class="panel pointer-events-auto max-w-[min(370px,calc(100vw-75px))] !rounded-2xl p-4">
        <h2 class="text-sm font-semibold">{{ spatial.mode === 'works' ? 'Участки работ' : 'После пожара' }}</h2>
        <template v-if="spatial.mode === 'works'">
          <p class="mt-1 text-xs text-muted-foreground">Предварительный план</p>
          <div v-if="spatial.work?.status === 'ready'" class="mt-3 space-y-2" aria-label="Легенда участков">
            <div v-for="item in spatial.work.totals" :key="item.action" class="flex items-center gap-2 text-xs">
              <i class="size-3 shrink-0 rounded-sm" :style="{ backgroundColor: WORK_COLORS[item.action], backgroundImage: ['agro', 'erosion', 'unknown'].includes(item.action) ? 'repeating-linear-gradient(135deg,transparent 0 3px,#fff8 3px 4px)' : undefined }" />
              <span class="flex-1">{{ item.label }}</span><span class="tabular-nums">{{ fmt.ha(item.area_ha) }} га</span>
            </div>
            <p v-if="!spatial.work.map?.features.length" class="text-xs text-muted-foreground">Нет участков для отображения</p>
          </div>
        </template>
        <template v-else-if="spatial.pairReady">
          <p class="mt-1 text-xs text-muted-foreground">{{ fmt.date(spatial.comparison!.post_fire!.date!) }} → {{ fmt.date(spatial.comparison!.recent!.date!) }}</p>
        </template>
        <button v-if="spatial.mode === 'compare'" class="mt-2 text-xs text-muted-foreground underline underline-offset-4" @click="spatial.history">История по годам</button>
        <p v-if="spatial.error || spatial.imageError" role="alert" class="mt-3 text-sm">{{ spatial.error || spatial.imageError }}</p>
        <Button v-if="spatial.error || spatial.imageError" class="mt-3" size="sm" variant="secondary" :disabled="spatial.loading" @click="spatial.retry">Повторить</Button>
        <div v-else-if="spatial.mode === 'works' ? spatial.work?.status !== 'ready' : !spatial.pairReady" role="status" class="mt-3 flex items-center gap-2 text-sm"><MorphLoader :size="22" />{{ spatial.mode === 'works' ? 'Готовим участки' : 'Подбираем снимки' }}</div>
      </div>
      <Button class="pointer-events-auto shadow-lg" variant="secondary" size="icon" aria-label="Закрыть режим карты" @click="spatial.close"><X /></Button>
    </div>
    <div v-if="spatial.mode === 'compare' && spatial.pairReady && !spatial.imageError" class="absolute bottom-0 top-0 w-px bg-white/80 shadow-lg" :style="{ left: `${spatial.split}%` }">
      <button role="slider" aria-label="Разделитель снимков" aria-valuemin="5" aria-valuemax="95" :aria-valuenow="Math.round(spatial.split)" class="pointer-events-auto absolute left-1/2 top-1/2 grid size-12 -translate-x-1/2 -translate-y-1/2 touch-none place-items-center rounded-full bg-primary text-primary-foreground shadow-lg outline-none focus-visible:ring-4 focus-visible:ring-ring" @pointerdown="drag" @pointermove="drag" @keydown.left.prevent="spatial.split = Math.max(5, spatial.split - 5)" @keydown.right.prevent="spatial.split = Math.min(95, spatial.split + 5)" @keydown.home.prevent="spatial.split = 5" @keydown.end.prevent="spatial.split = 95"><ChevronsLeftRight /></button>
      <span class="absolute right-3 top-[65%] whitespace-nowrap rounded-full bg-black/70 px-3 py-1 text-xs text-white">{{ fmt.date(spatial.comparison!.post_fire!.date!) }}</span>
      <span class="absolute left-3 top-[65%] whitespace-nowrap rounded-full bg-black/70 px-3 py-1 text-xs text-white">{{ fmt.date(spatial.comparison!.recent!.date!) }}</span>
    </div>
    <section v-if="spatial.mode === 'works' && spatial.selected" aria-label="Выбранный участок" class="panel pointer-events-auto absolute bottom-7 left-3 right-3 mx-auto max-w-sm !rounded-2xl p-4">
      <div class="flex items-start justify-between gap-3"><h3 class="text-sm font-semibold">{{ spatial.selected.properties.label }}</h3><span class="shrink-0 text-sm tabular-nums">{{ fmt.ha(spatial.selected.properties.area_ha) }} га</span></div>
      <p class="mt-1 text-xs text-muted-foreground">{{ spatial.selected.properties.landcover_label }} · {{ spatial.selected.properties.severity_label }} степень повреждения</p>
      <Button class="mt-3 w-full" size="sm" variant="secondary" @click="spatial.inspect">Назначить осмотр<ChevronRight /></Button>
    </section>
  </div>
</template>
