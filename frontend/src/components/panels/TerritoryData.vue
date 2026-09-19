<script setup lang="ts">
import { AlertTriangle, Check, Flame, LoaderCircle, Orbit, Satellite } from '@lucide/vue'
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'
import { plural } from '@/lib/format'
import type { AreaAcquisitionResult } from '@/lib/types'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'

const emit = defineEmits<{ openPeriod: [] }>()
const query = useQueryStore()
const live = useLiveStore()
const loading = ref(false)
const result = ref<AreaAcquisitionResult | null>(null)
const error = ref('')
const submittedJobs = ref<string[]>([])

const spanDays = computed(() => {
  const from = Date.parse(`${query.dateFrom}T00:00:00Z`)
  const to = Date.parse(`${query.dateTo}T00:00:00Z`)
  return Number.isFinite(from) && Number.isFinite(to) ? Math.round((to - from) / 86_400_000) : -1
})
const periodReady = computed(() => spanDays.value >= 0)
const runningJobs = computed(() => live.watchedJobs.filter(job => submittedJobs.value.includes(job.id) && !['done', 'failed'].includes(job.status)))
const finishedJobs = computed(() => live.watchedJobs.filter(job => submittedJobs.value.includes(job.id) && job.status === 'done').length)
const currentData = computed(() => {
  const report = query.report
  if (!report) return 'Проверяем покрытие…'
  return `${plural(report.hotspots.fire, ['термоточка', 'термоточки', 'термоточек'])}, ${plural(report.burn.contours, ['контур', 'контура', 'контуров'])}`
})

async function acquire() {
  if (!query.geometry || !periodReady.value) return
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const response = await api.acquire(query.geometry, query.dateFrom, query.dateTo)
    result.value = response
    submittedJobs.value = response.jobs.map(job => job.job_id)
    for (const job of response.jobs) {
      live.watch({ id: job.job_id, scene_id: job.scene_id, status: 'queued', stage: 'queued', progress: 0, message: 'В очереди RabbitMQ' })
    }
    await Promise.all([query.refreshMeta(), query.run()])
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить данные территории'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section aria-label="Данные выбранной территории" class="mt-3 overflow-hidden rounded-[22px] border border-border/70 bg-surface-2">
    <div class="p-3.5">
      <div class="flex items-start gap-3">
        <div class="grid size-9 shrink-0 place-items-center rounded-full bg-primary-container text-on-primary-container"><Orbit class="size-4.5" /></div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center justify-between gap-2">
            <h3 class="text-sm font-semibold text-wrap-balance">Данные территории</h3>
            <span class="shrink-0 text-[11px] tabular-nums text-muted-foreground">{{ spanDays }} дн.</span>
          </div>
          <p class="mt-0.5 text-xs leading-snug text-muted-foreground text-wrap-pretty">{{ currentData }}</p>
        </div>
      </div>

      <div class="mt-3 grid grid-cols-2 gap-1.5 text-[11px]">
        <div class="flex items-center gap-1.5 rounded-full bg-surface-3 px-2.5 py-1.5"><Flame class="size-3.5 text-fire" />Термоточки FIRMS</div>
        <div class="flex items-center gap-1.5 rounded-full bg-surface-3 px-2.5 py-1.5"><Satellite class="size-3.5 text-primary" />Гари Sentinel-2</div>
      </div>

      <p v-if="!periodReady" class="mt-3 rounded-xl bg-tertiary-container/60 px-3 py-2 text-xs leading-snug">
        Начало периода должно быть не позже окончания.
        <button type="button" class="font-medium underline underline-offset-2" @click="emit('openPeriod')">Изменить период</button>
      </p>
      <p v-else-if="!query.meta?.integrations.firms" class="mt-3 flex gap-2 rounded-xl bg-tertiary-container/60 px-3 py-2 text-xs leading-snug">
        <AlertTriangle class="mt-0.5 size-3.5 shrink-0" />Для термоточек серверу нужен бесплатный ключ NASA FIRMS. Гари можно загрузить уже сейчас.
      </p>

      <Button class="mt-3 w-full active:scale-[0.98]" :disabled="loading || !periodReady" @click="acquire">
        <LoaderCircle v-if="loading" class="animate-spin" />
        <Satellite v-else />
        {{ loading ? 'Получаем термоточки…' : query.report?.hotspots.fire || query.report?.burn.contours ? 'Обновить данные' : 'Получить данные' }}
      </Button>

      <div v-if="result" class="mt-3 space-y-2 border-t border-border/60 pt-3 text-xs" role="status">
        <div class="flex items-start gap-2">
          <Check v-if="result.hotspots.status === 'ready'" class="mt-0.5 size-3.5 shrink-0 text-tertiary" />
          <AlertTriangle v-else class="mt-0.5 size-3.5 shrink-0 text-destructive" />
          <span v-if="result.hotspots.status === 'ready'">
            Термоточки: {{ result.hotspots.imported ? `добавлено ${result.hotspots.imported}` : result.hotspots.existing ? 'уже загружены' : 'за период не найдены' }}.
          </span>
          <span v-else>Термоточки: {{ result.hotspots.message }}</span>
        </div>
        <div class="flex items-start gap-2">
          <LoaderCircle v-if="result.burns.status === 'queued' && runningJobs.length" class="mt-0.5 size-3.5 shrink-0 animate-spin text-primary" />
          <Check v-else-if="result.burns.status === 'queued'" class="mt-0.5 size-3.5 shrink-0 text-tertiary" />
          <AlertTriangle v-else class="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <span v-if="result.burns.status === 'queued'">
            Гари: {{ runningJobs.length ? `в обработке ${plural(runningJobs.length, ['чип', 'чипа', 'чипов'])}` : `${plural(finishedJobs || result.burns.jobs, ['чип', 'чипа', 'чипов'])} — в очереди или готовы` }}.
          </span>
          <span v-else>Гари не запущены: {{ result.burns.message }}</span>
        </div>
      </div>
      <p v-if="error" class="mt-3 text-xs leading-snug text-destructive" role="alert">{{ error }}</p>
    </div>
    <div class="border-t border-border/60 px-3.5 py-2 text-[10px] leading-snug text-muted-foreground">
      Термоточки можно загрузить за любой период; длинный период займёт больше времени. Детальная гарь строится для интервала 5–120 дней и участка до четырёх чипов 10,24 × 10,24 км.
    </div>
  </section>
</template>
