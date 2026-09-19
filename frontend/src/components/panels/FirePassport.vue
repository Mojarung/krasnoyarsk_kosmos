<script setup lang="ts">
import { ArrowLeft, ChevronLeft, ChevronRight, Columns2, Crosshair, Download, X } from '@lucide/vue'
import { onKeyStroke } from '@vueuse/core'
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import MorphLoader from '@/components/common/MorphLoader.vue'
import YandexMapsLink from '@/components/common/YandexMapsLink.vue'
import { useInspectionStore } from '@/stores/inspection'
import { PURPOSES, type Inspection } from '@/lib/inspections'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { fmt, plural } from '@/lib/format'
import type { FireEventList, FireEventStatus } from '@/lib/types'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const query = useQueryStore()
const live = useLiveStore()
const inspection = useInspectionStore()
const tasks = shallowRef<Inspection[]>([])
const tasksError = ref('')
let taskController: AbortController | null = null
async function loadTasks() {
  taskController?.abort()
  taskController = new AbortController()
  const signal = taskController.signal
  const eventId = ui.passport?.id
  tasks.value = []; tasksError.value = ''
  if (!eventId) return
  try { const result = await api.inspections(eventId, signal); if (!signal.aborted) tasks.value = result.items }
  catch { if (!signal.aborted) tasksError.value = 'Не удалось загрузить задания' }
}
watch(() => ui.passport?.id, loadTasks)
watch(() => inspection.event, (value) => { if (!value) void loadTasks() })
const list = shallowRef<FireEventList | null>(null)
const loading = ref(false)
const error = ref('')
const status = ref<FireEventStatus | 'all'>('all')
const offset = ref(0)
const scroller = ref<HTMLElement | null>(null)
const heading = ref<HTMLElement | null>(null)
const detail = computed(() => ui.passport)
const isList = computed(() => ui.passportTarget?.type === 'list')
const labels: Record<FireEventStatus, string> = {
  linked: 'Связь предполагается', hotspot_only: 'Только термоточки', burn_only: 'Только гарь', ambiguous: 'Связь неоднозначна',
}
const explanations: Record<FireEventStatus, string> = {
  linked: 'VIIRS заметил тепло рядом с этой гарью между снимками Sentinel «до» и «после». Совпадение места и времени — основание для связи, но не подтверждение.',
  hotspot_only: 'VIIRS заметил тепло. Подходящей гари Sentinel среди загруженных снимков нет. Это не означает, что территория не выгорела.',
  burn_only: 'Sentinel выявил повреждение растительности. Связанные термоточки VIIRS в загруженных наблюдениях не найдены.',
  ambiguous: 'Рядом и в подходящие даты найдено несколько событий Sentinel. Система оставила их раздельными — нужна проверка специалиста.',
}
let controller: AbortController | null = null
let generation = 0

async function load() {
  const target = ui.passportTarget
  if (!target || !query.params) return
  controller?.abort()
  controller = new AbortController()
  const signal = controller.signal
  const current = ++generation
  loading.value = true
  error.value = ''
  ui.passport = null
  list.value = null
  try {
    if (target.type === 'list') {
      const result = await api.events(query.params, status.value, offset.value, signal)
      if (current === generation) list.value = result
    } else {
      const id = target.type === 'event' ? target.id : (await api.resolveEvent(target, signal)).id
      const result = await api.event(id, signal)
      if (current === generation) ui.passport = result
    }
  } catch (e) {
    if (current === generation && !(e instanceof DOMException && e.name === 'AbortError')) {
      error.value = e instanceof Error ? e.message : 'Не удалось загрузить паспорт'
    }
  } finally {
    if (current === generation) {
      loading.value = false
      await nextTick()
      scroller.value?.scrollTo({ top: 0 })
      heading.value?.focus({ preventScroll: true })
    }
  }
}

function close() { ui.passportTarget = null }
function back() { ui.passportTarget = { type: 'list' } }
function open(id: string) { ui.passportTarget = { type: 'event', id } }
function download() {
  if (!detail.value) return
  const url = URL.createObjectURL(new Blob([JSON.stringify(detail.value, null, 2)], { type: 'application/json' }))
  Object.assign(document.createElement('a'), { href: url, download: `${detail.value.id}.json` }).click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
watch(() => ui.passportTarget, load, { immediate: true })
watch([status, offset], load)
watch(() => query.params, () => {
  offset.value = 0
  if (isList.value) void load()
  else back()
})
watch(() => live.dataVersion, load)
onKeyStroke('Escape', (e) => {
  if (ui.compareSceneId || ui.pipelineOpen || inspection.event) return
  e.preventDefault()
  if (isList.value) close()
  else back()
})
onBeforeUnmount(() => { generation++; controller?.abort(); taskController?.abort(); ui.passport = null })
</script>

<template>
  <section class="panel flex max-h-full w-[440px] max-w-full flex-col !bg-surface-1" aria-label="Паспорта пожаров" :aria-busy="loading">
    <header class="flex shrink-0 items-center gap-2 px-4 py-3">
      <Button v-if="!isList" variant="ghost" size="icon-sm" aria-label="Назад к паспортам" @click="back"><ArrowLeft /></Button>
      <h2 ref="heading" tabindex="-1" class="min-w-0 flex-1 text-base font-semibold outline-none">{{ isList ? 'Паспорта пожаров' : 'Паспорт пожара' }}</h2>
      <Button variant="ghost" size="icon-sm" aria-label="Закрыть паспорта" @click="close"><X /></Button>
    </header>

    <div ref="scroller" class="thin-scroll min-h-0 overflow-y-auto overscroll-contain px-5 pb-5">
      <template v-if="isList">
        <div class="mb-3 text-sm text-muted-foreground">{{ query.regionName }}<br>{{ fmt.date(query.dateFrom) }} — {{ fmt.date(query.dateTo) }}</div>
        <label for="event-status" class="mb-1 block text-sm">Наблюдения</label>
        <select id="event-status" :value="status" class="mb-3 h-10 w-full rounded-xl border bg-surface-2 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" @change="offset = 0; status = ($event.target as HTMLSelectElement).value as FireEventStatus | 'all'">
          <option value="all">Все события</option>
          <option value="linked">Термоточки и гарь</option>
          <option value="hotspot_only">Только термоточки</option>
          <option value="burn_only">Только гарь</option>
          <option value="ambiguous">Неоднозначная связь</option>
        </select>
      </template>

      <div v-if="loading" role="status" class="flex min-h-40 items-center justify-center gap-3"><MorphLoader :size="30" /><span class="text-sm">Собираем наблюдения</span></div>
      <div v-else-if="error" role="alert" class="py-6">
        <p class="text-sm">{{ error }}</p><Button class="mt-3" size="sm" variant="secondary" @click="load">Повторить</Button>
      </div>
      <template v-else-if="isList && list">
        <p v-if="!list.total" class="py-6 text-sm text-muted-foreground">Событий по этому запросу нет. Измените период, территорию или тип наблюдений.</p>
        <template v-else>
          <div class="mb-2 text-sm text-muted-foreground">{{ plural(list.total, ['событие', 'события', 'событий']) }}</div>
          <ol class="divide-y divide-border">
            <li v-for="item in list.items" :key="item.id">
              <button type="button" class="group w-full rounded-lg py-3 text-left outline-none hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-ring" :aria-label="`Открыть паспорт ${item.id}`" @click="open(item.id)">
                <span class="flex items-center justify-between gap-2 text-sm font-medium"><span>{{ fmt.date(item.first_seen ?? item.date_to) }}</span><ChevronRight class="size-4 shrink-0 text-muted-foreground" /></span>
                <span class="mt-1 block text-sm">{{ labels[item.status] }}</span>
                <span class="mt-1 block text-xs text-muted-foreground">{{ item.hotspot_count }} термоточек<span v-if="item.scene_ids.length">, {{ plural(item.scene_ids.length, ['снимок гари', 'снимка гари', 'снимков гари']) }}</span></span>
              </button>
            </li>
          </ol>
          <div class="mt-3 flex items-center justify-between gap-2">
            <Button variant="secondary" size="icon-sm" aria-label="Предыдущие события" :disabled="!offset" @click="offset = Math.max(0, offset - list.limit)"><ChevronLeft /></Button>
            <span class="text-sm tabular-nums">{{ offset + 1 }}–{{ Math.min(offset + list.limit, list.total) }} из {{ list.total }}</span>
            <Button variant="secondary" size="icon-sm" aria-label="Следующие события" :disabled="offset + list.limit >= list.total" @click="offset += list.limit"><ChevronRight /></Button>
          </div>
        </template>
      </template>

      <template v-else-if="detail">
        <div class="flex flex-wrap items-center gap-2">
          <span class="rounded-full bg-secondary px-3 py-1 text-sm font-medium">{{ labels[detail.status] }}</span>
          <span class="text-xs text-muted-foreground">{{ detail.id }}</span>
        </div>
        <p data-testid="passport-observation-date" class="mt-3 text-sm font-medium">
          <template v-if="detail.first_seen">Тепло замечено: {{ fmt.date(detail.first_seen) }}<template v-if="detail.last_seen?.slice(0, 10) !== detail.first_seen.slice(0, 10)"> — {{ fmt.date(detail.last_seen!) }}</template></template>
          <template v-else>Снимки: {{ fmt.date(detail.date_from) }} — {{ fmt.date(detail.date_to) }}</template>
        </p>
        <p class="mt-3 text-sm leading-relaxed">{{ explanations[detail.status] }}</p>

        <dl class="mt-4 grid grid-cols-2 gap-4 border-y py-4">
          <div><dt class="text-sm text-muted-foreground">Термоточки VIIRS</dt><dd class="mt-1 text-2xl font-semibold tabular-nums">{{ detail.hotspot_count || 'Нет данных' }}</dd></div>
          <div><dt class="text-sm text-muted-foreground">Гарь Sentinel</dt><dd class="mt-1 text-2xl font-semibold tabular-nums">{{ detail.burn ? fmt.ha(detail.burn.area_ha) : 'Нет данных' }}<span v-if="detail.burn" class="ml-1 text-sm font-normal">га</span></dd></div>
        </dl>
        <div class="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" @click="ui.passport = { ...detail }"><Crosshair />На карте</Button>
          <Button size="sm" variant="ghost" @click="download"><Download />Скачать JSON</Button>
        </div>
        <p class="mt-2 text-xs leading-relaxed text-muted-foreground">{{ detail.scope_note }}</p>
        <YandexMapsLink class="mt-4" :bounds="detail.bbox" place="Место наблюдений из паспорта" />

        <section v-if="detail.burn" class="mt-5 border-t pt-4" aria-label="Осмотры участка">
          <h3 class="text-sm font-semibold">Проверить на месте</h3>
          <Button class="mt-3 w-full" variant="tonal" @click="inspection.start(detail)">Запланировать осмотр</Button>
          <p v-if="tasksError" class="mt-2 text-xs" role="alert">{{ tasksError }} <button class="underline" @click="loadTasks">Повторить загрузку заданий</button></p>
          <button v-for="task in tasks" :key="task.id" type="button" class="mt-2 flex w-full items-center justify-between gap-3 rounded-xl bg-surface-2 p-3 text-left text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring" @click="inspection.start(detail, task)"><span>{{ PURPOSES[task.purpose] }}<span class="mt-1 block text-muted-foreground">{{ fmt.dateTimeUtc(task.created_at) }}</span></span><ChevronRight class="size-4 shrink-0" /></button>
        </section>

        <section class="mt-5" aria-label="История наблюдений">
          <h3 class="text-sm font-semibold">История наблюдений</h3>
          <p v-if="detail.observed_days" class="mt-1 text-sm text-muted-foreground">{{ plural(detail.observed_days, ['день с наблюдением', 'дня с наблюдениями', 'дней с наблюдениями']) }}. Между пролётами данных нет.</p>
          <ol class="mt-2 divide-y divide-border">
            <li v-for="observation in detail.timeline" :key="observation.at" class="py-3">
              <time class="text-sm font-medium">{{ fmt.dateTimeUtc(observation.at) }}</time>
              <div class="mt-1 text-sm"><span class="mr-2 inline-block size-2 rounded-full bg-fire" />{{ plural(observation.hotspot_count, ['термоточка', 'термоточки', 'термоточек']) }}, {{ observation.satellites.join(', ') || 'VIIRS' }}</div>
            </li>
            <li v-for="scene in detail.scenes" :key="scene.id" class="py-3">
              <div class="text-sm font-medium">{{ fmt.date(scene.date_post) }}: выявлена гарь</div>
              <div class="mt-1 text-sm text-muted-foreground">Сравнение с {{ fmt.date(scene.date_pre) }}<span v-if="scene.cloud_frac !== null">, облачность {{ fmt.pct(scene.cloud_frac) }}</span></div>
              <Button class="mt-2" size="sm" variant="secondary" :aria-label="`До и после ${scene.id}`" @click="ui.compareSceneId = scene.id"><Columns2 />До и после</Button>
            </li>
          </ol>
        </section>

        <section v-if="detail.burn" class="mt-5" aria-label="Степень поражения">
          <h3 class="text-sm font-semibold">Степень поражения</h3>
          <div class="mt-3 flex h-2 overflow-hidden rounded-full" aria-hidden="true"><span v-for="s in detail.burn.by_severity" :key="s.severity" :style="{ width: `${s.share * 100}%`, background: `var(--sev-${s.severity})` }" /></div>
          <div v-for="s in detail.burn.by_severity" :key="s.severity" class="mt-2 flex justify-between gap-2 text-sm"><span><i class="mr-2 inline-block size-2 rounded-full" :style="{ background: `var(--sev-${s.severity})` }" />{{ s.label }}</span><span class="tabular-nums">{{ fmt.ha(s.area_ha) }} га</span></div>
        </section>

        <section v-if="detail.restoration" class="mt-5" aria-label="План восстановления">
          <h3 class="text-sm font-semibold">План восстановления</h3>
          <p class="mt-2 text-xs leading-relaxed text-muted-foreground">{{ detail.restoration.note }}</p>
          <div v-for="item in detail.restoration.items" :key="item.action" class="mt-3 flex items-start justify-between gap-4 text-sm"><span>{{ item.label }}</span><span class="shrink-0 tabular-nums">{{ fmt.ha(item.area_ha) }} га</span></div>
        </section>

        <section v-if="detail.candidate_ids.length" class="mt-5">
          <h3 class="text-sm font-semibold">Возможные связи</h3>
          <button v-for="id in detail.candidate_ids" :key="id" type="button" class="mt-2 block text-sm underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring" @click="open(id)">{{ id }}</button>
        </section>
        <details class="mt-5 border-t pt-3">
          <summary class="cursor-pointer rounded text-sm font-medium focus-visible:ring-2 focus-visible:ring-ring">Как связаны данные</summary>
          <p class="mt-2 text-sm leading-relaxed text-muted-foreground">{{ detail.method.association }}</p>
          <p v-if="detail.evidence.length" class="mt-2 text-sm">{{ detail.evidence.length }} термоточек совпали с гарью по месту и датам. Ближайшая — {{ fmt.num(Math.min(...detail.evidence.map(e => e.distance_m))) }} м от контура.</p>
          <p class="mt-2 text-sm leading-relaxed text-muted-foreground">{{ detail.method.observation }}</p>
          <p class="mt-2 text-xs text-muted-foreground">Площадь — объединение контуров без повторного счёта. На пересечениях принята более сильная степень. Граница на карте упрощена для отображения.</p>
        </details>
      </template>
    </div>
  </section>
</template>
