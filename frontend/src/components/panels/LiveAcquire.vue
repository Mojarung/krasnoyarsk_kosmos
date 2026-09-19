<script setup lang="ts">
import { Dices, Flame, Satellite, SquareDashedMousePointer } from '@lucide/vue'
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'
import { plural } from '@/lib/format'
import type { AreaGeometry } from '@/lib/types'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'

const CHIP_KM = 10.24
const MAX_CHIPS = 4

const ui = useUiStore()
const live = useLiveStore()
const query = useQueryStore()

const geometry = ref<AreaGeometry | null>(null)
const label = ref('')
const datePre = ref('')
const datePost = ref('')
const busy = ref(false)
const message = ref<{ tone: 'ok' | 'error'; text: string } | null>(null)

const ready = computed(() => !!geometry.value && !!datePre.value && !!datePost.value)

async function suggest(mode: 'random' | 'fire') {
  busy.value = true
  message.value = null
  try {
    const hint = await api.suggestArea(mode)
    geometry.value = hint.geometry
    label.value = hint.label
    datePre.value = hint.date_pre
    datePost.value = hint.date_post
    const [lon, lat] = hint.geometry.coordinates[0][0]
    ui.flyTarget = { lon, lat, zoom: 10 }
  } catch (e) {
    message.value = { tone: 'error', text: e instanceof ApiError ? e.message : 'Сервис недоступен' }
  } finally {
    busy.value = false
  }
}

function useQueryArea() {
  if (!query.geometry) return
  geometry.value = query.geometry
  label.value = `Область запроса: ${query.regionName}`
}

async function submit() {
  if (!geometry.value) return
  busy.value = true
  message.value = null
  try {
    const { jobs } = await api.acquire(geometry.value, datePre.value, datePost.value)
    // Запрос переезжает на эту область и даты: когда чип обработается, сводка и карта обновятся сами.
    query.apply({ geometry: geometry.value, regionId: null, from: datePre.value, to: datePost.value })
    for (const job of jobs) live.watch({ id: job.job_id, scene_id: job.scene_id, status: 'queued', stage: 'queued', progress: 0, message: 'В очереди RabbitMQ' })
    message.value = { tone: 'ok', text: `В очереди ${plural(jobs.length, ['чип', 'чипа', 'чипов'])}. Скачивание идёт несколько минут, ход виден ниже. Готовая гарь появится на карте сама.` }
  } catch (e) {
    message.value = { tone: 'error', text: e instanceof ApiError ? e.message : 'Не удалось поставить в очередь' }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="space-y-3">
    <p class="text-[13px] leading-snug text-muted-foreground">
      Сервис сам найдёт в открытом каталоге ближайшие малооблачные сцены Sentinel-2 «до» и «после», соберёт чип в формате кейса
      ({{ CHIP_KM }} × {{ CHIP_KM }} км, 20 м) и проведёт его через ту же модель гарей. Большая область делится на чипы, не больше {{ MAX_CHIPS }}.
    </p>

    <div class="grid grid-cols-3 gap-1.5">
      <Button v-tip="'Случайная точка внутри зоны интереса и свежая пара дат'" size="sm" variant="secondary" :disabled="busy" @click="suggest('random')"><Dices />Случайная</Button>
      <Button v-tip="'Случайный очаг из архива термоточек: даты ставятся вокруг дня горения, так что гарь на снимке «после» скорее всего есть'" size="sm" variant="secondary" :disabled="busy" @click="suggest('fire')"><Flame />По очагу</Button>
      <Button v-tip="'Взять полигон или регион, выбранный сейчас в запросе'" size="sm" variant="secondary" :disabled="busy || !query.geometry" @click="useQueryArea"><SquareDashedMousePointer />Из запроса</Button>
    </div>

    <div class="flex items-center gap-2 rounded-2xl px-3 py-2 text-xs" :class="geometry ? 'bg-primary-container text-on-primary-container' : 'bg-surface-2 text-muted-foreground'">
      <Satellite class="size-3.5 shrink-0" /><span class="truncate">{{ label || 'Область не выбрана' }}</span>
    </div>

    <div class="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
      <label class="rounded-2xl bg-surface-2 px-3 py-2">Снимок до, примерно<input v-model="datePre" type="date" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none" /></label>
      <label class="rounded-2xl bg-surface-2 px-3 py-2">Снимок после, примерно<input v-model="datePost" type="date" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none" /></label>
    </div>

    <Button class="w-full" :disabled="busy || !ready" @click="submit">{{ busy ? 'Минуту...' : ready ? 'Скачать снимки и найти гарь' : 'Выберите область и даты' }}</Button>
    <p v-if="message" class="text-xs leading-snug" :class="message.tone === 'ok' ? 'text-tertiary' : 'text-destructive'">{{ message.text }}</p>
    <p class="text-[11px] leading-snug text-muted-foreground">
      Радар Sentinel-1 в открытом каталоге без авторизации недоступен: его каналы заполняются нейтральным значением, модель опирается на оптику.
      Режим показывает работу на новой территории и к тестовым чипам соревнования не применяется.
    </p>
  </div>
</template>
