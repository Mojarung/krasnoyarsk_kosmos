<script setup lang="ts">
import { gsap } from 'gsap'
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{ size?: number; label?: string }>(), { size: 56, label: '' })

const POINTS = 72
const RADIUS = 38
const SHAPES: [lobes: number, amplitude: number][] = [
  [0, 0],
  [4, 0.2],
  [6, 0.1],
  [3, 0.16],
  [8, 0.07],
]

const path = ref<SVGPathElement | null>(null)
const group = ref<SVGGElement | null>(null)
let timeline: gsap.core.Timeline | null = null
let spin: gsap.core.Tween | null = null

function radii([lobes, amplitude]: [number, number]): number[] {
  return Array.from({ length: POINTS }, (_, i) => RADIUS * (1 + amplitude * Math.cos((lobes * i * 2 * Math.PI) / POINTS)))
}

function toPath(values: number[]): string {
  const points = values.map((r, i) => {
    const angle = (i * 2 * Math.PI) / POINTS
    return [50 + r * Math.cos(angle), 50 + r * Math.sin(angle)]
  })
  const mid = (a: number[], b: number[]) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
  const start = mid(points[POINTS - 1], points[0])
  let d = `M${start[0].toFixed(2)} ${start[1].toFixed(2)}`
  for (let i = 0; i < POINTS; i++) {
    const next = mid(points[i], points[(i + 1) % POINTS])
    d += `Q${points[i][0].toFixed(2)} ${points[i][1].toFixed(2)} ${next[0].toFixed(2)} ${next[1].toFixed(2)}`
  }
  return `${d}Z`
}

onMounted(() => {
  const shapes = SHAPES.map(radii)
  const state = { values: [...shapes[0]] }
  const render = () => path.value?.setAttribute('d', toPath(state.values))
  render()
  timeline = gsap.timeline({ repeat: -1 })
  shapes.forEach((_, index) => {
    const target = shapes[(index + 1) % shapes.length]
    timeline!.to(state.values, { endArray: target, duration: 0.62, ease: 'back.inOut(1.6)', onUpdate: render }, '>0.08')
  })
  spin = gsap.to(group.value, { rotation: 360, duration: 3.4, ease: 'none', repeat: -1, svgOrigin: '50 50' })
})

onBeforeUnmount(() => {
  timeline?.kill()
  spin?.kill()
})
</script>

<template>
  <div class="inline-flex flex-col items-center gap-3" role="status" :aria-label="props.label || 'Загрузка'">
    <svg :width="props.size" :height="props.size" viewBox="0 0 100 100" aria-hidden="true">
      <g ref="group">
        <path ref="path" fill="var(--primary)" />
      </g>
    </svg>
    <span v-if="props.label" class="text-sm text-muted-foreground">{{ props.label }}</span>
  </div>
</template>
