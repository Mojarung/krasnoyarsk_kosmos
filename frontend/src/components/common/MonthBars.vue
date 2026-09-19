<script setup lang="ts">
import { computed } from 'vue'
import { fmt } from '@/lib/format'

export interface MonthPoint {
  month: string
  value: number
}

const props = withDefaults(
  defineProps<{
    items: MonthPoint[]
    title: string
    unit: string
    color?: string
    height?: number
    hint?: string
    format?: (value: number) => string
    /** Курсор общий на несколько графиков одной оси: null — курсора нет, показываем пик. */
    cursor?: number | null
    /** Подписи годов рисует только нижний график связки. */
    axis?: boolean
  }>(),
  { color: 'var(--primary)', height: 68, hint: undefined, format: (value: number) => fmt.int(value), cursor: null, axis: true },
)

const emit = defineEmits<{ 'update:cursor': [value: number | null] }>()

const peak = computed(() => Math.max(0, ...props.items.map((i) => i.value)))
const peakIndex = computed(() => props.items.findIndex((i) => i.value === peak.value))
const total = computed(() => props.items.reduce((sum, i) => sum + i.value, 0))
const at = computed(() => (props.cursor != null ? props.cursor : peakIndex.value))
const current = computed<MonthPoint | null>(() => props.items[at.value] ?? null)
const empty = computed(() => !props.items.length || peak.value <= 0)

/** Подписи годов под осью: первый месяц ряда и каждый январь. */
const years = computed(() =>
  props.items
    .map((item, index) => ({ item, index }))
    .filter(({ item, index }) => index === 0 || item.month.endsWith('-01'))
    .map(({ item, index }) => ({ label: item.month.slice(0, 4), index })),
)

/**
 * Высота столбика пропорциональна значению без всякого пола: прежние 8 % минимума
 * рисовали месяц с тремя точками почти таким же, как месяц с двумя тысячами.
 * Ненулевому значению оставлен только зрительный минимум в 2 px, иначе его не видно.
 */
function heightOf(value: number): string {
  if (peak.value <= 0 || value <= 0) return '1px'
  return `max(2px, ${(value / peak.value) * 100}%)`
}

function indexAt(event: PointerEvent): number | null {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  if (!rect.width || !props.items.length) return null
  const raw = Math.floor(((event.clientX - rect.left) / rect.width) * props.items.length)
  return Math.min(Math.max(raw, 0), props.items.length - 1)
}

function onMove(event: PointerEvent) {
  emit('update:cursor', indexAt(event))
}

function onKey(event: KeyboardEvent) {
  const last = props.items.length - 1
  if (last < 0) return
  const from = at.value < 0 ? 0 : at.value
  const next = { ArrowLeft: from - 1, ArrowRight: from + 1, Home: 0, End: last }[event.key]
  if (next == null) return
  event.preventDefault()
  emit('update:cursor', Math.min(Math.max(next, 0), last))
}
</script>

<template>
  <figure>
    <figcaption class="flex items-baseline justify-between gap-3">
      <span v-tip="props.hint" class="text-[13px] text-muted-foreground" :class="props.hint && 'term'">{{ props.title }}</span>
      <span v-if="!empty" class="shrink-0 text-[13px] text-muted-foreground">
        всего <span class="tabular-nums font-medium text-foreground">{{ props.format(total) }}</span> {{ props.unit }}
      </span>
    </figcaption>

    <div v-if="empty" class="mt-1 grid rounded-[14px] bg-surface-2 text-[13px] text-muted-foreground" :style="{ height: `${props.height + 22}px`, placeItems: 'center' }">
      За выбранный период данных нет
    </div>

    <template v-else>
      <div class="mt-0.5 flex items-baseline justify-between gap-3 text-[14px]">
        <span class="truncate font-medium">
          {{ current ? fmt.month(current.month) : '—' }}
          <span v-if="props.cursor === null" class="font-normal text-muted-foreground">— пик</span>
        </span>
        <span class="shrink-0 font-semibold tabular-nums">
          {{ current ? props.format(current.value) : '—' }}
          <span class="text-[13px] font-normal text-muted-foreground">{{ props.unit }}</span>
        </span>
      </div>

      <div
        class="relative mt-2 flex cursor-crosshair items-end gap-0.5 border-b border-border outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        :style="{ height: `${props.height}px` }"
        role="img"
        tabindex="0"
        :aria-label="`${props.title}: всего ${props.format(total)} ${props.unit}, пик ${fmt.month(props.items[peakIndex]?.month ?? '')}`"
        @pointermove="onMove"
        @pointerleave="emit('update:cursor', null)"
        @keydown="onKey"
        @blur="emit('update:cursor', null)"
      >
        <div
          v-for="(item, index) in props.items"
          :key="item.month"
          class="min-w-px flex-1 rounded-t-[4px] transition-[height] duration-500 ease-spring"
          :style="{
            height: heightOf(item.value),
            background: item.value > 0 ? props.color : 'var(--border)',
            outline: index === at ? '2px solid var(--background)' : undefined,
          }"
        />
        <span
          v-if="props.cursor !== null && at >= 0"
          class="pointer-events-none absolute inset-y-0 w-px bg-foreground/45"
          :style="{ left: `${((at + 0.5) / props.items.length) * 100}%` }"
        />
      </div>

      <div v-if="props.axis" class="relative mt-1.5 h-4 text-[13px] leading-none text-muted-foreground">
        <span v-for="year in years" :key="year.index" class="absolute tabular-nums" :style="{ left: `${(year.index / props.items.length) * 100}%` }">{{ year.label }}</span>
      </div>
    </template>
  </figure>
</template>
