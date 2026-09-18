import { useStorage } from '@vueuse/core'
import { defineStore } from 'pinia'
import { ref, shallowRef, watchEffect } from 'vue'

export type Basemap = 'dark' | 'satellite'
export type DrawMode = 'idle' | 'polygon' | 'rectangle'
export type InsightTab = 'report' | 'metrics' | 'restoration' | 'technogenic'

export const useUiStore = defineStore('ui', () => {
  const theme = useStorage<'dark' | 'light'>('fw-theme', 'dark')
  const basemap = useStorage<Basemap>('fw-basemap', 'dark')
  const showFiltered = ref(true)
  const showSeverity = ref(true)
  const showSources = ref(false)
  const drawMode = ref<DrawMode>('idle')
  const insightTab = ref<InsightTab>('report')
  const insightOpen = ref(true)
  const queryOpen = ref(true)
  const pipelineOpen = ref(false)
  const compareSceneId = ref<string | null>(null)
  const playing = ref(false)
  const playhead = ref<number | null>(null)
  const flyTarget = shallowRef<{ lon: number; lat: number; zoom?: number } | null>(null)

  watchEffect(() => document.documentElement.classList.toggle('dark', theme.value === 'dark'))

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  return {
    theme, basemap, showFiltered, showSeverity, showSources, drawMode, insightTab, insightOpen, queryOpen,
    pipelineOpen, compareSceneId, playing, playhead, flyTarget, toggleTheme,
  }
})
