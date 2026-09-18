<script setup lang="ts" generic="T extends string">
import { useResizeObserver } from '@vueuse/core'
import { gsap } from 'gsap'
import { nextTick, onMounted, ref, watch, type Component } from 'vue'
import { cn } from '@/lib/utils'

export interface BubbleOption<V extends string> {
  value: V
  label: string
  icon?: Component
  badge?: string | number
}

const props = withDefaults(defineProps<{ options: BubbleOption<T>[]; size?: 'sm' | 'md'; stretch?: boolean }>(), {
  size: 'md',
  stretch: false,
})
const model = defineModel<T>({ required: true })

const root = ref<HTMLElement | null>(null)
const bubble = ref<HTMLElement | null>(null)
const buttons = ref<HTMLElement[]>([])
let placed = false

function move(animate: boolean) {
  const index = props.options.findIndex((o) => o.value === model.value)
  const target = buttons.value[index]
  if (!target || !bubble.value) return
  const next = { x: target.offsetLeft, width: target.offsetWidth }
  if (!animate || !placed) {
    gsap.set(bubble.value, { ...next, opacity: 1 })
    placed = true
    return
  }
  const current = Number(gsap.getProperty(bubble.value, 'x'))
  const stretchTo = Math.abs(next.x - current) * 0.35 + next.width
  gsap
    .timeline({ defaults: { overwrite: 'auto' } })
    .to(bubble.value, { x: Math.min(current, next.x), width: stretchTo, scaleY: 0.86, duration: 0.16, ease: 'power2.out' })
    .to(bubble.value, { ...next, scaleY: 1, duration: 0.55, ease: 'elastic.out(1, 0.62)' })
}

onMounted(() => nextTick(() => move(false)))
watch(model, () => move(true), { flush: 'post' })
watch(() => props.options.length, () => nextTick(() => move(false)))
useResizeObserver(root, () => move(false))
</script>

<template>
  <div
    ref="root"
    role="tablist"
    :class="cn('relative inline-flex items-center rounded-full bg-surface-3/70 p-1', props.stretch && 'flex w-full')"
  >
    <span
      ref="bubble"
      aria-hidden="true"
      class="pointer-events-none absolute left-0 top-1 bottom-1 rounded-full bg-primary-container opacity-0 will-change-transform"
    />
    <button
      v-for="option in props.options"
      :key="option.value"
      :ref="(el) => el && (buttons[props.options.indexOf(option)] = el as HTMLElement)"
      type="button"
      role="tab"
      :aria-selected="model === option.value"
      :class="
        cn(
          'relative z-10 inline-flex items-center justify-center gap-1.5 rounded-full font-medium whitespace-nowrap outline-none transition-colors duration-300 focus-visible:ring-2 focus-visible:ring-ring/60',
          props.size === 'sm' ? 'h-7 px-3 text-xs' : 'h-9 px-4 text-[13px]',
          props.stretch && 'flex-1',
          model === option.value ? 'text-on-primary-container' : 'text-muted-foreground hover:text-foreground',
        )
      "
      @click="model = option.value"
    >
      <component :is="option.icon" v-if="option.icon" class="size-3.5 shrink-0" />
      <span>{{ option.label }}</span>
      <span v-if="option.badge != null" class="rounded-full bg-background/50 px-1.5 text-[10px] leading-4">{{ option.badge }}</span>
    </button>
  </div>
</template>
