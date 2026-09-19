import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { api } from '@/lib/api'
import type { FireEventDetail } from '@/lib/types'
import type { VegetationReport } from '@/lib/vegetation'
import type { WorkMap, WorkProps } from '@/lib/work-map'
import type { Coordinates } from '@/lib/inspections'
import { useUiStore } from './ui'
import { useInspectionStore } from './inspection'

export const useSpatialStore = defineStore('spatial', () => {
  const mode = ref<'works' | 'compare' | null>(null)
  const event = shallowRef<FireEventDetail | null>(null)
  const work = shallowRef<WorkMap | null>(null)
  const comparison = shallowRef<VegetationReport | null>(null)
  const selected = shallowRef<{ properties: WorkProps; point: Coordinates } | null>(null)
  const split = ref(50)
  const error = ref('')
  const loading = ref(false)
  const imageError = ref('')
  const pairReady = computed(() => !!comparison.value?.georef && comparison.value?.post_fire?.status === 'ready' && comparison.value?.recent?.status === 'ready')
  let controller: AbortController | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let generation = 0

  function close() {
    generation++; controller?.abort(); clearTimeout(timer)
    mode.value = null; event.value = null; work.value = null; comparison.value = null
    selected.value = null; loading.value = false; error.value = ''; imageError.value = ''
  }
  async function load(start: boolean, retry = false) {
    if (!event.value || !mode.value) return
    const current = generation, id = event.value.id, kind = mode.value
    controller?.abort(); controller = new AbortController()
    const signal = controller.signal
    loading.value = true; error.value = ''
    try {
      if (kind === 'works') {
        const result = start ? await api.startWorkMap(id, signal) : await api.workMap(id, signal)
        if (current !== generation) return
        work.value = result
        if (result.status === 'error') error.value = result.message ?? 'Не удалось подготовить участки'
        else if (result.status !== 'ready') timer = setTimeout(() => void load(false), 2000)
      } else {
        const result = start || !comparison.value ? await api.startVegetation(id, retry, signal) : await api.vegetation(comparison.value.id, signal)
        if (current !== generation) return
        comparison.value = result
        if (!pairReady.value) {
          if (['queued', 'running'].includes(result.status)) timer = setTimeout(() => void load(false), 2000)
          else error.value = result.recent?.message ?? result.message ?? 'Нет пригодной пары снимков для сравнения'
        }
      }
    } catch (e) {
      if (!signal.aborted && current === generation) error.value = e instanceof Error ? e.message : 'Не удалось загрузить данные'
    } finally { if (current === generation) loading.value = false }
  }
  function open(value: FireEventDetail, kind: 'works' | 'compare') {
    close()
    const ui = useUiStore()
    ui.vegetationEvent = null; ui.compareSceneId = null; ui.playing = false
    event.value = value; mode.value = kind; split.value = 50
    void load(true)
  }
  function retry() { clearTimeout(timer); imageError.value = ''; void load(true, true) }
  function inspect() {
    if (!event.value || !selected.value) return
    const inspection = useInspectionStore()
    inspection.start(event.value)
    inspection.purpose = 'recovery'; inspection.site = selected.value.point
    inspection.note = `${selected.value.properties.label}: ${selected.value.properties.landcover_label}, ${selected.value.properties.severity_label} степень повреждения. Предварительный план.`
    close()
  }
  function history() {
    const value = event.value
    close()
    useUiStore().vegetationEvent = value
  }
  return { mode, event, work, comparison, selected, split, error, imageError, loading, pairReady, open, close, retry, inspect, history }
})
