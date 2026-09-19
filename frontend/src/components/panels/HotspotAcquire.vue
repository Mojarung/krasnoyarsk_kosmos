<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Satellite, ChevronRight } from '@lucide/vue'
import { api, type HotspotAcquisition } from '@/lib/api'
import { Button } from '@/components/ui/button'
import MorphLoader from '@/components/common/MorphLoader.vue'

const props = defineProps<{ eventId: string }>()
const emit = defineEmits<{ open: [id: string] }>()
const state = ref<HotspotAcquisition | null>(null)
const busy = ref(false)
const error = ref('')
let controller: AbortController | null = null
let timer: ReturnType<typeof setTimeout> | undefined
const running = computed(() => state.value?.status === 'running')
const message = computed(() => {
  if (running.value) {
    const job = state.value?.jobs.find(j => j.status !== 'done')
    return job?.stage === 'queued' ? 'В очереди' : ['acquire', 'fetch'].includes(job?.stage ?? '') ? 'Подбираем и загружаем снимки' : 'Определяем контур гари'
  }
  if (state.value?.status === 'failed') return state.value.jobs.find(j => j.error)?.error ?? 'Не удалось обработать снимки'
  if (state.value?.status === 'not_found') return 'Снимки проверены. Гарь рядом с термоточками не выявлена.'
  return ''
})
async function load(start = false) {
  clearTimeout(timer)
  controller?.abort()
  controller = new AbortController()
  const signal = controller.signal
  const id = props.eventId
  busy.value = true
  error.value = ''
  try {
    const result = start
      ? await api.startHotspotAcquisition(id, state.value?.status === 'failed', signal)
      : await api.hotspotAcquisition(id, signal)
    if (signal.aborted) return
    state.value = result
    if (result.status === 'running') timer = setTimeout(() => void load(), 3000)
  } catch (e) {
    if (!signal.aborted) error.value = e instanceof Error ? e.message : 'Не удалось проверить загрузку'
  } finally { if (!signal.aborted) busy.value = false }
}
watch(() => props.eventId, () => { state.value = null; void load() }, { immediate: true })
onBeforeUnmount(() => { controller?.abort(); clearTimeout(timer) })
</script>

<template>
  <section class="mt-4 rounded-xl bg-surface-2 p-3" aria-label="Поиск гари по снимкам">
    <div v-if="running || (!state && busy)" role="status" class="flex items-center gap-3 text-sm">
      <MorphLoader :size="22" /><span>{{ message || 'Проверяем загрузку' }}</span>
    </div>
    <template v-else-if="state?.status === 'found' || state?.status === 'ambiguous'">
      <Button class="w-full" size="sm" variant="secondary" @click="state.event_id && emit('open', state.event_id)">{{ state.status === 'found' ? 'Открыть найденную гарь' : 'Проверить варианты связи' }}<ChevronRight /></Button>
    </template>
    <template v-else>
      <p v-if="message" class="text-sm" role="status">{{ message }}</p>
      <Button v-if="state && state.status !== 'not_found'" class="w-full" :class="{ 'mt-3': message }" size="sm" variant="secondary" :disabled="busy" @click="load(true)"><Satellite />{{ busy ? 'Запускаем поиск' : state.status === 'failed' ? 'Повторить поиск' : 'Найти гарь по снимкам' }}</Button>
    </template>
    <p v-if="error" role="alert" class="mt-2 text-sm">{{ error }} <button class="underline" :disabled="busy" @click="load()">Повторить</button></p>
  </section>
</template>
