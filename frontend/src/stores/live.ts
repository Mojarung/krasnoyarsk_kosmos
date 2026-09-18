import { useDebounceFn } from '@vueuse/core'
import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { api } from '@/lib/api'
import type { AlertItem, JobEvent, PipelineMetrics, Zone } from '@/lib/types'
import { useQueryStore } from './query'

const MAX_JOBS = 14
const REFRESH_DEBOUNCE_MS = 2500

export const useLiveStore = defineStore('live', () => {
  const connected = ref(false)
  const jobs = ref<JobEvent[]>([])
  const jobCounts = ref<Record<string, number>>({})
  const alerts = ref<AlertItem[]>([])
  const unread = ref(0)
  const zones = shallowRef<Zone[]>([])
  const toast = ref<AlertItem | null>(null)
  const metrics = shallowRef<PipelineMetrics | null>(null)
  const dataVersion = ref(0)
  let source: EventSource | null = null

  const activeJobs = computed(() => jobs.value.filter((j) => j.status === 'running' || j.status === 'queued'))
  const pending = computed(() => (jobCounts.value.queued ?? 0) + (jobCounts.value.running ?? 0))

  const refreshData = useDebounceFn(async () => {
    const query = useQueryStore()
    dataVersion.value += 1
    await Promise.all([query.refreshMeta(), query.run(), loadJobs()])
  }, REFRESH_DEBOUNCE_MS)

  function upsertJob(job: JobEvent) {
    const rest = jobs.value.filter((j) => j.id !== job.id)
    jobs.value = [job, ...rest].slice(0, MAX_JOBS)
  }

  async function loadJobs() {
    const [list, pipeline] = await Promise.all([api.jobs(), api.pipelineMetrics()])
    jobCounts.value = list.counts
    metrics.value = pipeline
    if (!jobs.value.length) jobs.value = list.items
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
      upsertJob(job)
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
    connected, jobs, jobCounts, alerts, unread, zones, toast, metrics, dataVersion, activeJobs, pending,
    connect, loadJobs, loadZones, markRead,
  }
})
