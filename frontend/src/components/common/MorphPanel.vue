<script setup lang="ts">
import { gsap } from 'gsap'
import { Flip } from 'gsap/Flip'
import { nextTick, ref, watch } from 'vue'
import { cn } from '@/lib/utils'

gsap.registerPlugin(Flip)

const props = defineProps<{ open: boolean; class?: string; pillClass?: string }>()
const shell = ref<HTMLElement | null>(null)
const body = ref<HTMLElement | null>(null)
const expanded = ref(props.open)

watch(
  () => props.open,
  async (open) => {
    if (!shell.value) return
    const state = Flip.getState(shell.value)
    expanded.value = open
    await nextTick()
    Flip.from(state, { duration: 0.62, ease: 'expo.out', scale: false, simple: true })
    if (body.value) gsap.fromTo(body.value, { opacity: 0, y: open ? 10 : 0 }, { opacity: 1, y: 0, duration: 0.4, delay: 0.12, ease: 'power2.out' })
  },
)
</script>

<template>
  <section ref="shell" :class="cn('panel pointer-events-auto overflow-hidden', expanded ? props.class : cn('!rounded-full', props.pillClass))">
    <div ref="body" class="flex min-h-0 flex-1 flex-col">
      <slot v-if="expanded" />
      <slot v-else name="pill" />
    </div>
  </section>
</template>
