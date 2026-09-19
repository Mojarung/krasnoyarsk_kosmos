<script setup lang="ts">
import { ArrowLeft, MapPin, RefreshCw } from '@lucide/vue'
import { onKeyStroke } from '@vueuse/core'
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import MorphLoader from '@/components/common/MorphLoader.vue'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { fmt } from '@/lib/format'
import type { FireEventDetail } from '@/lib/types'
import type { VegetationReport } from '@/lib/vegetation'
import { useUiStore } from '@/stores/ui'
import { useInspectionStore } from '@/stores/inspection'

const props = defineProps<{ event: FireEventDetail }>()
const ui = useUiStore()
const inspection = useInspectionStore()
const report = shallowRef<VegetationReport | null>(null)
const pending = ref(false)
const error = ref('')
const selected = ref<number | null>(null)
const mode = ref<'rgb' | 'change'>('rgb')
const paired = ref(false)
const split = ref(50)
const imageError = ref(false)
const imageLoaded = ref(false)
const baseLoaded = ref(false)
const baseError = ref(false)
const revision = ref(0)
const title = ref<HTMLElement | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | null = null
let stopped = false
let generation = 0
const working = computed(() => report.value?.status === 'running' || report.value?.status === 'queued')
const frame = computed(() => report.value?.frames.find(f => f.year === selected.value))
const base = computed(() => report.value?.frames.find(f => f.year === report.value?.baseline_year && f.role === 'before' && f.rgb_url))
const comparison = computed(() => frame.value?.comparison)
const retryable = computed(() => report.value?.frames.some(f => f.status === 'error' || f.status === 'missing'))
const canCompare = computed(() => !!(base.value && frame.value?.rgb_url && frame.value.year !== base.value.year))
const isPair = computed(() => paired.value && canCompare.value && mode.value === 'rgb')
const baseUrl = computed(() => base.value?.rgb_url ? `${base.value.rgb_url}?v=${revision.value}` : '')
const available = computed(() => report.value?.frames.filter(f => f.rgb_url).length ?? 0)
const imageUrl = computed(() => {
  const url = mode.value === 'change' ? frame.value?.change_url : frame.value?.rgb_url
  return url ? `${url}?v=${revision.value}` : ''
})
const role = computed(() => ({ before: 'До пожара', during: 'В период пожара', after: 'После пожара' })[frame.value?.role ?? 'after'])
const delta = computed(() => {
  const value = comparison.value?.delta_ndvi
  return value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2).replace('.', ',')}`
})
const tabs = computed(() => [{ value: 'rgb' as const, label: 'Снимок' }, ...(frame.value?.change_url ? [{ value: 'change' as const, label: 'Растительность' }] : [])])
const comparisonNote = computed(() => {
  if (comparison.value?.delta_ndvi != null) return `К ${fmt.date(comparison.value.baseline_date)} · ${fmt.ha(comparison.value.compared_ha)} га`
  if ((comparison.value?.season_gap_days ?? 0) > 14) return 'Даты съёмки отличаются больше чем на 14 дней по сезону'
  if (comparison.value) return 'Меньше 80% общих наблюдений — итог не рассчитан'
  if (frame.value?.role === 'before') return 'Снимок до пожара — исходное состояние'
  return working.value ? 'Готовим сравнение со снимком до пожара' : 'Нет пригодного снимка до пожара для сравнения'
})
function yearLabel(year: number) {
  const f = report.value?.frames.find(f => f.year === year)
  if (f?.status === 'error') return 'ошибка'
  if (f?.status === 'missing') return 'нет снимка'
  if (f?.status === 'cloudy') return 'частично'
  if (f) return f.role === 'before' ? 'до пожара' : 'готово'
  return report.value?.active_year === year ? 'загрузка' : 'ожидает'
}

function accept(value: VegetationReport) {
  report.value = value
  if (selected.value === null) selected.value = value.years.at(-1) ?? null
  clearTimeout(timer)
  if (working.value && !stopped) timer = setTimeout(() => poll(generation), 2000)
}
async function poll(current: number) {
  if (!report.value || stopped) return
  try {
    const value = await api.vegetation(report.value.id, controller?.signal)
    if (!stopped && current === generation) { error.value = ''; accept(value) }
  } catch (e) {
    if (!stopped && current === generation) {
      error.value = e instanceof Error ? e.message : 'Не удалось обновить наблюдения'
      timer = setTimeout(() => poll(current), 5000)
    }
  }
}
async function load(retry = false) {
  clearTimeout(timer)
  const current = ++generation
  controller?.abort()
  controller = new AbortController()
  pending.value = true; error.value = ''
  try {
    const value = await api.startVegetation(props.event.id, retry, controller.signal)
    if (!stopped && current === generation) accept(value)
  } catch (e) {
    if (!stopped && current === generation) error.value = e instanceof Error ? e.message : 'Не удалось загрузить наблюдения'
  } finally { if (!stopped && current === generation) pending.value = false }
}
function choose(year: number) { selected.value = year; mode.value = 'rgb' }
function close() { ui.vegetationEvent = null }
function inspect() { inspection.start(props.event); inspection.purpose = 'recovery'; close() }
watch(imageUrl, () => { imageLoaded.value = false; imageError.value = false })
watch(baseUrl, () => { baseLoaded.value = false; baseError.value = false })
onMounted(() => { title.value?.focus(); void load() })
onBeforeUnmount(() => { stopped = true; controller?.abort(); clearTimeout(timer) })
onKeyStroke('Escape', e => { e.preventDefault(); close() })
</script>

<template>
  <section class="panel flex h-full w-[600px] max-w-full flex-col !bg-surface-1" role="dialog" aria-modal="false" aria-label="Растительность после пожара">
    <header class="flex shrink-0 items-center gap-3 px-4 py-3">
      <Button variant="ghost" size="icon-sm" aria-label="Вернуться в паспорт" @click="close"><ArrowLeft /></Button>
      <div class="min-w-0 flex-1"><h2 ref="title" tabindex="-1" class="text-base font-semibold outline-none">После пожара</h2><p class="text-xs text-muted-foreground">{{ fmt.date(event.date_to) }}<span class="ml-3">{{ fmt.ha(event.burn!.area_ha) }} га</span></p></div>
    </header>
    <div class="thin-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
      <div v-if="error" role="alert" class="mb-3 text-sm">{{ error }}<Button class="ml-2" size="sm" variant="secondary" @click="load()">Повторить</Button></div>
      <div v-if="!report && pending" role="status" class="flex min-h-52 items-center justify-center gap-3"><MorphLoader :size="28" /><span class="text-sm">Ищем снимки</span></div>
      <template v-if="report">
        <div class="mb-3 flex flex-wrap gap-1" role="group" aria-label="Год наблюдения">
          <button v-for="year in report.years" :key="year" type="button" :aria-pressed="selected === year" :aria-label="`Снимок за ${year} год`" class="min-h-11 min-w-14 flex-1 rounded-xl px-1 py-2 text-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring" :class="selected === year ? 'bg-primary font-semibold text-primary-foreground' : 'bg-surface-2 hover:bg-surface-3'" @click="choose(year)">{{ year }}<span class="block text-[10px] leading-3">{{ yearLabel(year) }}</span></button>
        </div>

        <div v-if="working" class="mb-3 flex items-center gap-2 text-xs text-muted-foreground" role="status"><MorphLoader :size="16" />{{ report.status === 'queued' ? 'В очереди' : `Загружаем ${report.active_year}` }}<span class="ml-auto tabular-nums">Снимков {{ available }} / {{ report.years.length }}</span></div>
        <div v-if="report.status === 'error'" class="mb-3 text-sm" role="alert">{{ report.message }}<Button class="mt-2" size="sm" variant="secondary" @click="load(true)">Повторить загрузку</Button></div>

        <template v-if="frame?.rgb_url">
          <div class="mb-3 flex items-center justify-between gap-3 rounded-xl bg-surface-2 px-3 py-2" data-testid="vegetation-summary">
            <div v-if="comparison" class="shrink-0"><div class="text-[10px] text-muted-foreground">Изменение NDVI</div><div class="text-xl font-semibold tabular-nums">{{ delta }}</div></div>
            <p class="text-xs text-muted-foreground">{{ comparisonNote }}</p>
          </div>
          <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
            <BubbleTabs v-model="mode" :options="tabs" size="sm" />
            <label v-if="canCompare && mode === 'rgb'" class="flex min-h-8 items-center gap-2 text-xs"><Switch v-model="paired" :aria-label="`Сравнить с ${report.baseline_year}`" />Сравнить с {{ report.baseline_year }}</label>
          </div>
          <div class="relative mx-auto h-[clamp(180px,36dvh,320px)] w-full overflow-hidden rounded-2xl bg-surface-3 max-sm:h-[clamp(160px,27dvh,220px)]" data-testid="vegetation-image">
            <img v-if="isPair" :key="baseUrl" :src="baseUrl" :alt="`Территория до пожара, ${base!.date}`" class="absolute inset-0 size-full object-contain" draggable="false" @load="baseLoaded = true" @error="baseError = true" />
            <img :key="imageUrl" :src="imageUrl" :alt="`${mode === 'rgb' ? 'Спутниковый снимок' : 'Изменение NDVI'} ${frame.date}`" class="absolute inset-0 size-full object-contain" :style="isPair ? { clipPath: `inset(0 0 0 ${split}%)` } : undefined" draggable="false" @load="imageLoaded = true" @error="imageError = true" />
            <template v-if="isPair"><div class="pointer-events-none absolute inset-y-0 w-px bg-white" :style="{ left: `${split}%` }" /><span class="absolute left-2 top-2 rounded-lg bg-black/70 px-2 py-1 text-xs text-white">{{ base!.date }}</span></template>
            <span class="absolute right-2 top-2 rounded-lg bg-black/70 px-2 py-1 text-xs text-white">{{ frame.date }}</span>
            <div v-if="(!imageLoaded || (isPair && !baseLoaded)) && !imageError && !(isPair && baseError)" class="absolute inset-0 grid place-items-center bg-surface-3"><MorphLoader :size="28" label="Открываем снимок" /></div>
            <div v-if="imageError || (isPair && baseError)" role="alert" class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-surface-3 text-sm"><span>Снимок не загрузился</span><Button size="sm" variant="secondary" @click="revision++">Повторить снимок</Button></div>
          </div>
          <input v-if="isPair" v-model.number="split" type="range" min="0" max="100" aria-label="Граница сравнения снимков" class="mt-3 w-full accent-primary" />
          <div class="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>{{ role }}</span><span>Доступно {{ fmt.pct(frame.valid_share!) }} гари</span></div>
          <div v-if="mode === 'change'" class="mt-3">
            <div class="h-2 rounded-full vegetation-scale" aria-hidden="true" /><div class="mt-1 flex justify-between text-xs"><span>Меньше зелени</span><span>Без изменений</span><span>Больше</span></div>
          </div>
          <p v-if="frame.status === 'cloudy'" class="mt-3 text-xs">Часть гари закрыта облаками или исключена маской качества.</p>
        </template>
        <div v-else class="flex min-h-56 flex-col items-center justify-center gap-3 text-center text-sm" role="status">
          <MorphLoader v-if="working && !frame" :size="28" />
          <p>{{ frame?.message ?? (working ? `Снимок ${selected} ещё загружается` : 'Наблюдение недоступно') }}</p>
          <p v-if="working && !frame" class="text-xs text-muted-foreground">Можно закрыть — загрузка продолжится</p>
        </div>

        <Button v-if="report.status === 'partial' && retryable" class="mt-3" size="sm" variant="ghost" :disabled="pending" @click="load(true)"><RefreshCw />Догрузить пропуски</Button>
      </template>
    </div>
    <footer class="shrink-0 border-t px-4 py-3"><Button class="w-full" size="sm" variant="secondary" @click="inspect"><MapPin />Осмотреть участок</Button></footer>
  </section>
</template>
