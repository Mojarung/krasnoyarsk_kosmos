import { useStorage } from '@vueuse/core'
import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watchEffect } from 'vue'

export type Basemap = 'dark' | 'satellite'
export type DrawMode = 'idle' | 'polygon' | 'rectangle'
export type InsightView = 'overview' | 'dynamics' | 'restoration' | 'alarms'
export type DayNight = 'all' | 'day' | 'night'

export interface DisplayFilters {
  severities: number[]
  minContourHa: number
  dayNight: DayNight
  minConfidence: number
  satellites: string[]
}

export const DEFAULT_FILTERS: DisplayFilters = { severities: [1, 2, 3], minContourHa: 0, dayNight: 'all', minConfidence: 0, satellites: [] }

export const useUiStore = defineStore('ui', () => {
  const theme = useStorage<'dark' | 'light'>('fw-theme', 'dark')
  const basemap = useStorage<Basemap>('fw-basemap', 'dark')
  const showFiltered = ref(true)
  const showSeverity = ref(true)
  const showSources = ref(false)
  const drawMode = ref<DrawMode>('idle')
  const insightTab = ref<InsightView>('overview')
  const insightOpen = ref(true)
  const queryOpen = ref(true)
  const pipelineOpen = ref(false)
  const compareSceneId = ref<string | null>(null)
  const playing = ref(false)
  const playhead = ref<number | null>(null)
  const flyTarget = shallowRef<{ lon: number; lat: number; zoom?: number } | null>(null)
  const filters = ref<DisplayFilters>({ ...DEFAULT_FILTERS })
  const activeFilterCount = computed(
    () =>
      Number(filters.value.severities.length < 3) +
      Number(filters.value.minContourHa > 0) +
      Number(filters.value.dayNight !== 'all') +
      Number(filters.value.minConfidence > 0) +
      Number(filters.value.satellites.length > 0),
  )

  function resetFilters() {
    filters.value = { ...DEFAULT_FILTERS, severities: [...DEFAULT_FILTERS.severities] }
  }

  watchEffect(() => document.documentElement.classList.toggle('dark', theme.value === 'dark'))

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  return {
    theme, basemap, showFiltered, showSeverity, showSources, drawMode, insightTab, insightOpen, queryOpen,
    pipelineOpen, compareSceneId, playing, playhead, flyTarget, filters, activeFilterCount, toggleTheme, resetFilters,
  }
})
