<script setup lang="ts">
import { CalendarDays } from '@lucide/vue'
import { computed, ref } from 'vue'
import { fmt } from '@/lib/format'

const props = defineProps<{ label: string; min?: string; max?: string; hint?: string }>()
const model = defineModel<string>({ required: true })
const input = ref<HTMLInputElement | null>(null)

const text = computed(() => (model.value ? fmt.date(model.value).replace(/\s*г\.$/, '') : 'не задано'))

function open() {
  const element = input.value
  if (!element) return
  if (typeof element.showPicker === 'function') element.showPicker()
  else element.focus()
}

function onChange(event: Event) {
  const value = (event.target as HTMLInputElement).value
  if (value) model.value = value
}
</script>

<template>
  <button
    v-tip="props.hint"
    type="button"
    class="relative flex w-full items-center justify-between gap-2 rounded-2xl bg-surface-3 px-3 py-2 text-left outline-none transition-colors duration-200 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/60"
    @click="open"
  >
    <span class="min-w-0">
      <span class="block text-[11px] leading-none text-muted-foreground">{{ props.label }}</span>
      <span class="mt-1 block truncate text-[13px] font-medium leading-tight tabular-nums">{{ text }}</span>
    </span>
    <CalendarDays class="size-4 shrink-0 text-muted-foreground" />
    <input ref="input" type="date" tabindex="-1" aria-hidden="true" class="pointer-events-none absolute inset-0 size-full opacity-0" :value="model" :min="props.min" :max="props.max" @change="onChange" />
  </button>
</template>
