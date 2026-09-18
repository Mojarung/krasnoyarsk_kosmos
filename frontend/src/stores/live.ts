import { useDebounceFn, useIntervalFn } from '@vueuse/core'
import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { api } from '@/lib/api'
import type { AlertItem, JobEvent, PipelineMetrics, Zone } from '@/lib/types'
import { useQueryStore } from './query'

const REFRESH_DEBOUNCE_MS = 2500
const POLL_MS = 2500
const MAX_WATCHED = 8

export const useLiveStore = defineStore('live', () => {
  const connected = ref(false)
  const jobsById = ref<Record<string, JobEvent>>({})
  const watchedIds = ref<string[]>([])
  const running = shallowRef<string[]>([])
  const jobCounts = ref<Record<string, number>>({})
  const alerts = ref<AlertItem[]>([])
  const unread = ref(0)
  const zones = shallowRef<Zone[]>([])
  const toast = ref<AlertItem | null>(null)
  const metrics = shallowRef<PipelineMetrics | null>(null)
  const dataVersion = ref(0)
  let source: EventSource | null = null

  const pending = computed(() => (jobCounts.value.queued ?? 0) + (jobCounts.value.running ?? 0))
  const total = computed(() => Object.values(jobCounts.value).reduce((sum, n) => sum + n, 0))
  const watchedJobs = computed(() => watchedIds.value.map((id) => jobsById.value[id]).filter(Boolean))

  const refreshData = useDebounceFn(async () => {
    const query = useQueryStore()
    dataVersion.value += 1
    await Promise.all([query.refreshMeta(), query.run()])
  }, REFRESH_DEBOUNCE_MS)

  async function loadJobs() {
    const [list, pipeline] = await Promise.all([api.jobs(), api.pipelineMetrics()])
    jobCounts.value = list.counts
    metrics.value = pipeline
    running.value = list.items.filter((j) => j.status === 'running').map((j) => j.scene_id).slice(0, 3)
  }

  useIntervalFn(() => {
    if (pending.value > 0) void loadJobs()
  }, POLL_MS)

  function watch(job: JobEvent) {
    jobsById.value = { ...jobsById.value, [job.id]: job }
    watchedIds.value = [job.id, ...watchedIds.value.filter((id) => id !== job.id)].slice(0, MAX_WATCHED)
    void loadJobs()
  }

  async function loadZones() {
    const [zoneList, alertList] = await Promise.all([api.zones(), api.alerts()])
    zones.value = zoneList
    alerts.value = alertList.items
    unread.value = alertList.unread
  }

  function connect() {
    source?.close()
    source = new EventSource('/api/v1/stream')
    source.addEventListener('hello', () => (connected.value = true))
    source.addEventListener('job', (e) => {
      const job = JSON.parse((e as MessageEvent).data) as JobEvent
      if (watchedIds.value.includes(job.id)) jobsById.value = { ...jobsById.value, [job.id]: job }
      if (job.status === 'queued' && pending.value === 0) void loadJobs()
      if (job.status === 'done' || job.status === 'failed') void refreshData()
    })
    source.addEventListener('alert', (e) => {
      const alert = JSON.parse((e as MessageEvent).data) as AlertItem
      alerts.value = [alert, ...alerts.value]
      unread.value += 1
      toast.value = alert
    })
    source.onerror = () => (connected.value = false)
  }

  async function markRead() {
    if (!unread.value) return
    unread.value = 0
    await api.markAlertsRead()
  }

  return {
    connected, jobCounts, running, alerts, unread, zones, toast, metrics, dataVersion, pending, total, watchedJobs,
    connect, loadJobs, loadZones, markRead, watch,
  }
})
