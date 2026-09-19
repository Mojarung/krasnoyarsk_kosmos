import { useStorage } from '@vueuse/core'
import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watchEffect } from 'vue'

export type Basemap = 'dark' | 'satellite'
export type DrawMode = 'idle' | 'polygon' | 'rectangle'
export type InsightView = 'overview' | 'dynamics' | 'emissions' | 'profile' | 'restoration' | 'alarms'
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
  /* На узком экране панели стартуют свёрнутыми: две развёрнутые заняли бы всю
     карту, а карта здесь главный объект. Порог совпадает с брейкпоинтом lg. */
  const wide = typeof window === 'undefined' || window.innerWidth >= 1024
  const insightOpen = ref(wide)
  const queryOpen = ref(wide)
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

  /**
   * Новая тема раскрывается кругом из самой кнопки переключения — через View
   * Transitions снимок старого экрана остаётся на месте, а новый выезжает
   * из точки нажатия. Радиус берём до самого дальнего угла, иначе круг
   * не накроет экран целиком.
   *
   * Запасной путь для браузеров без View Transitions и для reduced-motion —
   * класс theme-anim: переход цветов на 700 мс, снимается сразу. Постоянный
   * transition на background-color висеть не может: он делает вялым отклик
   * на наведение.
   */
  let themeAnimTimer: ReturnType<typeof setTimeout> | undefined
  function flip() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }
  function fade() {
    const root = document.documentElement
    root.classList.add('theme-anim')
    clearTimeout(themeAnimTimer)
    themeAnimTimer = setTimeout(() => root.classList.remove('theme-anim'), 780)
    flip()
  }

  function toggleTheme(origin?: { x: number; y: number }) {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const start = document.startViewTransition?.bind(document)
    if (!start || reduced || !origin) {
      if (reduced) flip()
      else fade()
      return
    }
    const { x, y } = origin
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y))
    const transition = start(() => {
      flip()
    })
    void transition.ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 1200, easing: 'cubic-bezier(0.2, 0, 0, 1)', pseudoElement: '::view-transition-new(root)' },
      )
    })
  }

  return {
    theme, basemap, showFiltered, showSeverity, showSources, drawMode, insightTab, insightOpen, queryOpen,
    pipelineOpen, compareSceneId, playing, playhead, flyTarget, filters, activeFilterCount, toggleTheme, resetFilters,
  }
})
