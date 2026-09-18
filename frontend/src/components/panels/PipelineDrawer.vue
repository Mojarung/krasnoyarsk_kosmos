<script setup lang="ts">
import { FileUp, RefreshCw, UploadCloud } from '@lucide/vue'
import { computed, onMounted, ref } from 'vue'
import BubbleTabs from '@/components/common/BubbleTabs.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { api, ApiError } from '@/lib/api'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import JobRow from './JobRow.vue'

type Kind = 'af' | 'bs'

const ui = useUiStore()
const live = useLiveStore()
const query = useQueryStore()

const KINDS = [
  { value: 'bs' as const, label: 'Гарь (Sentinel)' },
  { value: 'af' as const, label: 'Горение (VIIRS)' },
]
const ROLE_PATTERNS: [role: string, pattern: RegExp][] = [
  ['viirs', /viirs/i],
  ['s2_pre', /sentinel-?2_pre/i],
  ['s2_post', /sentinel-?2_post/i],
  ['s1_pre', /sentinel-?1_pre/i],
  ['s1_post', /sentinel-?1_post/i],
  ['mask', /mask/i],
  ['aux', /aux/i],
]
const REQUIRED: Record<Kind, string[]> = { af: ['viirs', 'aux'], bs: ['s2_pre', 's2_post', 's1_pre', 's1_post', 'aux'] }
const ROLE_LABELS: Record<string, string> = {
  viirs: 'VIIRS I1-I5', aux: 'Вспомогательные слои', s2_pre: 'Sentinel-2 до', s2_post: 'Sentinel-2 после',
  s1_pre: 'Sentinel-1 до', s1_post: 'Sentinel-1 после', mask: 'Эталон (необязательно)',
}

const kind = ref<Kind>('bs')
const files = ref<Record<string, File>>({})
const acquiredAt = ref('')
const datePre = ref('')
const datePost = ref('')
const dragging = ref(false)
const sending = ref(false)
const message = ref<{ tone: 'ok' | 'error'; text: string } | null>(null)

const stages = computed(() => query.meta?.pipeline ?? [])
const roles = computed(() => [...REQUIRED[kind.value], 'mask'])
const missing = computed(() => REQUIRED[kind.value].filter((role) => !files.value[role]))
const doneShare = computed(() => (live.total ? ((live.jobCounts.done ?? 0) / live.total) * 100 : 0))
const datesReady = computed(() => (kind.value === 'af' ? !!acquiredAt.value : !!datePre.value && !!datePost.value))

function track(result: { job_id: string; scene_id: string }) {
  live.watch({ id: result.job_id, scene_id: result.scene_id, status: 'queued', stage: 'queued', progress: 0, message: 'В очереди RabbitMQ' })
}

function assign(list: FileList | null) {
  if (!list) return
  const next = { ...files.value }
  for (const file of Array.from(list)) {
    const role = ROLE_PATTERNS.find(([, pattern]) => pattern.test(file.name))?.[0]
    if (role) next[role] = file
  }
  files.value = next
  if (next.viirs) kind.value = 'af'
  else if (next.s2_post) kind.value = 'bs'
}

function onDrop(event: DragEvent) {
  dragging.value = false
  assign(event.dataTransfer?.files ?? null)
}

async function submit() {
  const form = new FormData()
  form.set('kind', kind.value)
  if (kind.value === 'af') form.set('acquired_at', new Date(acquiredAt.value).toISOString())
  else {
    form.set('date_pre', datePre.value)
    form.set('date_post', datePost.value)
  }
  for (const role of roles.value) if (files.value[role]) form.set(role, files.value[role])
  sending.value = true
  message.value = null
  try {
    const result = await api.uploadScene(form)
    track(result)
    message.value = { tone: 'ok', text: `Сцена ${result.scene_id} в очереди. Ход обработки ниже.` }
    files.value = {}
  } catch (e) {
    message.value = { tone: 'error', text: e instanceof ApiError ? e.message : 'Не удалось загрузить' }
  } finally {
    sending.value = false
  }
}

async function replayRandom() {
  const pick = kind.value
  const list = await api.scenes({ kind: pick, status: 'ready', limit: '40' })
  const scene = list.items[Math.floor(Math.random() * list.items.length)]
  if (scene) track(await api.reprocess(scene.id))
}

onMounted(() => live.loadJobs())
</script>

<template>
  <Dialog v-model:open="ui.pipelineOpen">
    <DialogContent class="panel max-h-[88dvh] w-[min(560px,94vw)] max-w-none gap-0 overflow-hidden !rounded-[32px] border-border p-0">
      <DialogHeader class="px-6 pt-6">
        <DialogTitle class="text-lg">Конвейер обработки</DialogTitle>
        <DialogDescription class="text-[13px]">Файлы уходят в S3, задание в RabbitMQ, воркер пишет результат в PostGIS. Прогресс приходит по SSE.</DialogDescription>
      </DialogHeader>

      <div class="thin-scroll space-y-4 overflow-y-auto px-6 pb-6 pt-4">
        <div class="flex items-center justify-between gap-3">
          <BubbleTabs v-model="kind" :options="KINDS" size="sm" />
          <Button v-tip="'Берёт случайную готовую сцену и проводит её через весь конвейер заново. Удобно показать живой ход обработки без файлов под рукой'" size="sm" variant="secondary" @click="replayRandom"><RefreshCw />Прогнать готовую сцену</Button>
        </div>

        <label
          class="flex cursor-pointer flex-col items-center gap-2 rounded-[26px] border-2 border-dashed px-5 py-6 text-center transition-[border-color,background-color,border-radius] duration-300 ease-spring"
          :class="dragging ? 'rounded-[40px] border-primary bg-primary/10' : 'border-border hover:border-primary/60'"
          @dragover.prevent="dragging = true"
          @dragleave="dragging = false"
          @drop.prevent="onDrop"
        >
          <UploadCloud class="size-7 text-primary" />
          <span class="text-sm font-medium">Перетащите GeoTIFF-файлы чипа</span>
          <span class="text-xs text-muted-foreground">Роли определяются по именам: VIIRS, Sentinel-2_pre, AUX, MASK</span>
          <input type="file" multiple accept=".tif,.tiff" class="sr-only" @change="assign(($event.target as HTMLInputElement).files)" />
        </label>

        <div class="grid grid-cols-2 gap-1.5">
          <div v-for="role in roles" :key="role" class="flex items-center gap-2 rounded-full px-3 py-1.5 text-xs" :class="files[role] ? 'bg-primary-container text-on-primary-container' : 'bg-surface-2 text-muted-foreground'">
            <FileUp class="size-3.5 shrink-0" /><span class="truncate">{{ files[role]?.name ?? ROLE_LABELS[role] }}</span>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
          <label v-if="kind === 'af'" class="col-span-2 rounded-2xl bg-surface-2 px-3 py-2">Момент пролёта (UTC)<input v-model="acquiredAt" type="datetime-local" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none" /></label>
          <template v-else>
            <label class="rounded-2xl bg-surface-2 px-3 py-2">Снимок до<input v-model="datePre" type="date" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none" /></label>
            <label class="rounded-2xl bg-surface-2 px-3 py-2">Снимок после<input v-model="datePost" type="date" class="mt-0.5 block w-full bg-transparent text-sm text-foreground outline-none" /></label>
          </template>
        </div>

        <Button class="w-full" :disabled="sending || missing.length > 0 || !datesReady" @click="submit">
          {{ sending ? 'Загружаем...' : missing.length ? `Не хватает файлов: ${missing.length}` : datesReady ? 'Отправить в обработку' : 'Укажите даты съёмки' }}
        </Button>
        <p v-if="message" class="text-xs" :class="message.tone === 'ok' ? 'text-tertiary' : 'text-destructive'">{{ message.text }}</p>

        <div class="rounded-[22px] bg-surface-2 p-4">
          <div class="flex items-baseline justify-between text-[13px]">
            <span class="font-medium">Обработано {{ live.jobCounts.done ?? 0 }} из {{ live.total }}</span>
            <span class="text-xs text-muted-foreground">{{ live.pending ? `в очереди ${live.pending}` : 'очередь пуста' }}</span>
          </div>
          <div class="mt-2.5 h-2 overflow-hidden rounded-full bg-surface-3">
            <div class="h-full rounded-full bg-primary transition-[width] duration-700 ease-emphasized" :style="{ width: `${doneShare}%` }" />
          </div>
          <div class="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span class="truncate">{{ live.running.length ? `Сейчас: ${live.running.join(', ')}` : 'Воркеры ждут новые сцены' }}</span>
            <span v-if="live.metrics" class="shrink-0 tabular-nums">{{ live.metrics.scenes_last_minute }} сцен/мин</span>
          </div>
          <p v-if="live.jobCounts.failed" class="mt-1.5 text-xs text-destructive">С ошибкой: {{ live.jobCounts.failed }}</p>
        </div>

        <div v-if="live.watchedJobs.length">
          <div class="label-caps mb-2">Ваши запуски</div>
          <div class="space-y-1.5">
            <JobRow v-for="job in live.watchedJobs" :key="job.id" :job="job" :stages="stages" />
          </div>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
