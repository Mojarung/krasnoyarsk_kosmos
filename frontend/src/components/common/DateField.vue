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
  if (element && typeof element.showPicker === 'function') element.showPicker()
}

function onChange(event: Event) {
  const value = (event.target as HTMLInputElement).value
  if (value) model.value = value
}
</script>

<template>
  <!--
    Контролом служит сам input: раньше он лежал внутри <button>, и два
    интерактивных элемента вкладывались друг в друга — axe помечает это как
    nested-interactive, а скринридер объявляет кнопку, внутри которой поле.
    Теперь обёртка — label, input прозрачный и растянут на всю площадь,
    поэтому клик в любое место открывает календарь, а Tab попадает на поле.
  -->
  <label
    v-tip="props.hint"
    class="relative flex w-full cursor-pointer items-center justify-between gap-2 rounded-2xl bg-surface-3 px-3 py-2 text-left transition-colors duration-200 hover:bg-accent focus-within:ring-2 focus-within:ring-ring/60"
  >
    <span class="min-w-0">
      <span class="block text-[12px] leading-none text-muted-foreground">{{ props.label }}</span>
      <span class="mt-1 block truncate text-[13px] font-medium leading-tight tabular-nums">{{ text }}</span>
    </span>
    <CalendarDays class="size-4 shrink-0 text-muted-foreground" />
    <input
      ref="input"
      type="date"
      class="absolute inset-0 size-full cursor-pointer opacity-0"
      :aria-label="props.label"
      :value="model"
      :min="props.min"
      :max="props.max"
      @change="onChange"
      @click="open"
    />
  </label>
</template>
