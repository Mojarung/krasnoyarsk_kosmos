<script setup lang="ts">
import { ChevronsLeftRight, Layers, RefreshCw, X } from '@lucide/vue'
import { computed, ref, shallowRef, watch } from 'vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import MorphLoader from '@/components/common/MorphLoader.vue'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { fmt } from '@/lib/format'
import type { SceneSummary } from '@/lib/types'
import { useLiveStore } from '@/stores/live'
import { useUiStore } from '@/stores/ui'

type Composite = 'rgb' | 'swir' | 'sar' | 'dnbr'
interface Confusion { tp: number; fp: number; fn: number }

const emit = defineEmits<{ quicklook: [name: string] }>()
const ui = useUiStore()
const live = useLiveStore()

const COMPOSITES = [
  { value: 'rgb' as const, label: 'Видимый', hint: 'Естественные цвета, каналы B4-B3-B2' },
  { value: 'swir' as const, label: 'SWIR', hint: 'B12-B8A-B4: гарь тёмно-красная, растительность зелёная' },
  { value: 'sar' as const, label: 'Радар', hint: 'Sentinel-1 VV, VH и их разность. Видит сквозь дым и облака' },
  { value: 'dnbr' as const, label: 'dNBR', hint: 'Разность индекса гарей до и после: чем теплее цвет, тем сильнее поражение' },
]

const scene = shallowRef<SceneSummary | null>(null)
const composite = ref<Composite>('swir')
const showSeverity = ref(true)
const viewer = ref<HTMLElement | null>(null)
const loaded = ref(0)

const isBurn = computed(() => scene.value?.kind === 'bs')
const isPair = computed(() => isBurn.value && composite.value !== 'dnbr')
const before = computed(() => (scene.value ? api.quicklookUrl(scene.value.id, isBurn.value ? `${composite.value}_pre` : 'thermal') : ''))
const after = computed(() => {
  if (!scene.value) return ''
  if (!isBurn.value) return api.quicklookUrl(scene.value.id, 'thermal')
  return api.quicklookUrl(scene.value.id, composite.value === 'dnbr' ? 'dnbr' : `${composite.value}_post`)
})
const stats = computed(() => (scene.value?.stats ?? {}) as { burn_ha?: number; severity_ha?: number[]; contours?: number; quality?: { burn: Confusion } })
const iou = computed(() => {
  const c = stats.value.quality?.burn
  return c && c.tp + c.fp + c.fn > 0 ? c.tp / (c.tp + c.fp + c.fn) : null
})

watch(
  () => ui.compareSceneId,
  async (id) => {
    scene.value = null
    loaded.value = 0
    if (id) scene.value = await api.scene(id)
  },
  { immediate: true },
)
watch(composite, (value) => {
  loaded.value = 0
  emit('quicklook', value === 'dnbr' ? 'dnbr' : `${value}_post`)
})

function onPointer(event: PointerEvent) {
  if (!viewer.value || (event.type === 'pointermove' && event.buttons === 0)) return
  const rect = viewer.value.getBoundingClientRect()
  const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1)
  viewer.value.style.setProperty('--split', `${ratio * 100}%`)
}

async function reprocess() {
  if (!scene.value) return
  const result = await api.reprocess(scene.value.id)
  live.watch({ id: result.job_id, scene_id: result.scene_id, status: 'queued', stage: 'queued', progress: 0, message: 'В очереди RabbitMQ' })
  ui.pipelineOpen = true
}
</script>

<template>
  <section class="panel flex w-[min(560px,94vw)] flex-col gap-3 p-4" aria-label="Сравнение снимков до и после">
    <header class="flex items-center justify-between gap-3">
      <div class="min-w-0">
        <div class="truncate text-sm font-semibold">{{ scene?.id ?? 'Загрузка сцены' }}</div>
        <div v-if="scene?.date_pre && scene.date_post" class="text-xs text-muted-foreground">{{ fmt.date(scene.date_pre) }} → {{ fmt.date(scene.date_post) }} · облачность {{ fmt.pct(scene.cloud_frac) }}</div>
      </div>
      <div class="flex shrink-0 items-center gap-1">
        <Button v-tip="'Прогнать сцену через конвейер заново'" variant="ghost" size="icon-sm" aria-label="Обработать сцену заново" @click="reprocess"><RefreshCw /></Button>
        <Button v-tip="'Закрыть и вернуться к запросу'" variant="secondary" size="icon-sm" aria-label="Закрыть сравнение" @click="ui.compareSceneId = null"><X /></Button>
      </div>
    </header>

    <div
      ref="viewer"
      class="relative mx-auto aspect-square h-[min(46dvh,440px)] touch-none overflow-hidden rounded-[24px] bg-surface-3 select-none [--split:50%]"
      :class="isPair && 'cursor-ew-resize'"
      @pointerdown="isPair && onPointer($event)"
      @pointermove="isPair && onPointer($event)"
    >
      <template v-if="scene">
        <img v-if="isPair" :src="before" alt="Снимок до пожара" class="absolute inset-0 size-full object-cover" draggable="false" @load="loaded++" />
        <img :src="after" alt="Снимок после пожара" class="absolute inset-0 size-full object-cover" :style="isPair ? { clipPath: 'inset(0 0 0 var(--split))' } : undefined" draggable="false" @load="loaded++" />
        <img
          v-if="isBurn"
          :src="api.quicklookUrl(scene.id, 'severity')"
          alt=""
          class="absolute inset-0 size-full object-cover transition-opacity duration-500 [image-rendering:pixelated]"
          :class="showSeverity ? 'opacity-90' : 'opacity-0'"
          :style="isPair ? { clipPath: 'inset(0 0 0 var(--split))' } : undefined"
          draggable="false"
        />
        <template v-if="isPair">
          <div class="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-white/90 shadow-[0_0_14px_rgb(0_0_0/0.6)]" style="left: var(--split)">
            <span class="absolute top-1/2 left-1/2 grid size-9 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white text-black shadow-lg"><ChevronsLeftRight class="size-4" /></span>
          </div>
          <span class="pointer-events-none absolute left-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-[11px] text-white">до</span>
          <span class="pointer-events-none absolute right-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-[11px] text-white">после</span>
        </template>
      </template>
      <div v-if="!scene || loaded === 0" class="absolute inset-0 grid place-items-center bg-surface-3"><MorphLoader label="Достаём снимки из S3" /></div>
    </div>

    <div v-if="isBurn" class="flex flex-wrap items-center justify-between gap-2">
      <BubbleTabs v-model="composite" :options="COMPOSITES" size="sm" />
      <label v-tip="'Наложить полигоны степеней поражения на снимок'" class="flex items-center gap-2 text-xs text-muted-foreground"><Layers class="size-3.5" />степени<Switch v-model="showSeverity" /></label>
    </div>

    <div v-if="isBurn && stats.burn_ha != null" class="grid grid-cols-4 gap-1.5 text-center text-xs">
      <div class="rounded-2xl bg-surface-2 py-2"><div class="text-sm font-semibold tabular-nums">{{ fmt.ha(stats.burn_ha) }}</div><div class="text-muted-foreground">га гари</div></div>
      <div v-for="(value, index) in stats.severity_ha ?? []" :key="index" class="rounded-2xl bg-surface-2 py-2">
        <div class="text-sm font-semibold tabular-nums" :style="{ color: `var(--sev-${index + 1})` }">{{ fmt.ha(value) }}</div>
        <div class="text-muted-foreground">{{ ['слабая', 'средняя', 'сильная'][index] }}</div>
      </div>
    </div>
    <p v-if="iou != null" class="text-center text-[11px] text-muted-foreground">IoU контура с эталоном: {{ iou.toFixed(3) }} · модель {{ scene?.model_name }}</p>
  </section>
</template>
