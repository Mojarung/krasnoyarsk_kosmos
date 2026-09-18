<script setup lang="ts">
import { gsap } from 'gsap'
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ value: number; format?: (value: number) => string; duration?: number }>(), {
  format: (value: number) => Math.round(value).toLocaleString('ru-RU'),
  duration: 0.9,
})

const state = { current: 0 }
const text = ref(props.format(0))
let tween: gsap.core.Tween | null = null

watch(
  () => props.value,
  (value) => {
    tween?.kill()
    tween = gsap.to(state, {
      current: value,
      duration: props.duration,
      ease: 'power3.out',
      onUpdate: () => (text.value = props.format(state.current)),
    })
  },
  { immediate: true },
)

onBeforeUnmount(() => tween?.kill())
</script>

<template>
  <span class="tabular-nums">{{ text }}</span>
</template>
