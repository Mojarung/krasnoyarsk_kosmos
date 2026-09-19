import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { api, ApiError } from '@/lib/api'
import type { AreaGeometry, Meta, Profile, QueryResult, ResponsePlan, TimelineDay } from '@/lib/types'

export const AOI_REGION_ID = 'aoi'
const FALLBACK_RANGE = { from: '2019-04-01', to: '2024-11-30' }
const RESPONSE_POLL_MS = 7000
const RESPONSE_POLL_LIMIT = 25

export const useQueryStore = defineStore('query', () => {
  const meta = shallowRef<Meta | null>(null)
  const timeline = shallowRef<TimelineDay[]>([])
  const geometry = shallowRef<AreaGeometry | null>(null)
  const regionId = ref<string | null>(AOI_REGION_ID)
  const dateFrom = ref(FALLBACK_RANGE.from)
  const dateTo = ref(FALLBACK_RANGE.to)
  const result = shallowRef<QueryResult | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const profile = shallowRef<Profile | null>(null)
  const responsePlan = shallowRef<ResponsePlan | null>(null)
  let controller: AbortController | null = null
  let profileController: AbortController | null = null
  let responseController: AbortController | null = null
  let responseTimer: ReturnType<typeof setTimeout> | undefined

  const report = computed(() => result.value?.report ?? null)
  const params = computed(() =>
    geometry.value ? { geometry: geometry.value, date_from: dateFrom.value, date_to: dateTo.value } : null,
  )
  const regionName = computed(() => {
    if (regionId.value === AOI_REGION_ID) return meta.value?.aoi.properties.name ?? 'Вся территория'
    const region = meta.value?.regions.features.find((f) => f.properties.id === regionId.value)
    return region?.properties.name ?? 'Свой полигон'
  })

  async function bootstrap() {
    const [metaValue, timelineValue] = await Promise.all([api.meta(), api.timeline()])
    meta.value = metaValue
    timeline.value = timelineValue
    dateFrom.value = metaValue.data.date_min ?? FALLBACK_RANGE.from
    dateTo.value = metaValue.data.date_max ?? FALLBACK_RANGE.to
    geometry.value = metaValue.aoi.geometry
    await run()
  }

  async function refreshMeta() {
    const [metaValue, timelineValue] = await Promise.all([api.meta(), api.timeline()])
    meta.value = metaValue
    timeline.value = timelineValue
  }

  async function run() {
    if (!params.value) return
    controller?.abort()
    controller = new AbortController()
    loading.value = true
    error.value = null
    profile.value = null
    responsePlan.value = null
    clearTimeout(responseTimer)
    try {
      result.value = await api.query(params.value, controller.signal)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof ApiError ? e.message : 'Сервис недоступен'
    } finally {
      loading.value = false
    }
  }

  /** Профиль территории считается по всем годам и запрашивается отдельно: он нужен, только когда открыта вкладка. */
  async function loadProfile() {
    if (!params.value) return
    profileController?.abort()
    profileController = new AbortController()
    try {
      profile.value = await api.profile(params.value, profileController.signal)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof ApiError ? e.message : 'Сервис недоступен'
    }
  }

  /** План реагирования ходит во внешние справочники и на холодном кеше считается десятки секунд, поэтому грузится по требованию. */
  async function loadResponsePlan(attempt = 0) {
    if (!params.value) return
    clearTimeout(responseTimer)
    responseController?.abort()
    responseController = new AbortController()
    try {
      const plan = await api.responsePlan(params.value, responseController.signal)
      responsePlan.value = plan
      // Сёла, дороги и пожарные части сервер дозапрашивает у OpenStreetMap в фоне.
      if (plan.external.osm === 'pending' && attempt < RESPONSE_POLL_LIMIT) {
        responseTimer = setTimeout(() => void loadResponsePlan(attempt + 1), RESPONSE_POLL_MS)
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof ApiError ? e.message : 'Сервис недоступен'
    }
  }

  function selectRegion(id: string) {
    const source = id === AOI_REGION_ID ? meta.value?.aoi : meta.value?.regions.features.find((f) => f.properties.id === id)
    if (!source) return
    regionId.value = id
    geometry.value = source.geometry
    void run()
  }

  function setCustomGeometry(value: AreaGeometry) {
    regionId.value = null
    geometry.value = value
    void run()
  }

  function setPeriod(from: string, to: string) {
    dateFrom.value = from
    dateTo.value = to
    void run()
  }

  function apply(next: { geometry: AreaGeometry; regionId: string | null; from: string; to: string }) {
    geometry.value = next.geometry
    regionId.value = next.regionId
    dateFrom.value = next.from
    dateTo.value = next.to
    void run()
  }

  return {
    meta, timeline, geometry, regionId, dateFrom, dateTo, result, report, params, loading, error, regionName,
    profile, loadProfile, responsePlan, loadResponsePlan,
    bootstrap, refreshMeta, run, selectRegion, setCustomGeometry, setPeriod, apply,
  }
})
