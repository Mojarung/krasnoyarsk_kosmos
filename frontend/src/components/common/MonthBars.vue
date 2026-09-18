<script setup lang="ts">
import { computed, ref } from 'vue'
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
  }>(),
  { color: 'var(--primary)', height: 52, hint: undefined, format: (value: number) => fmt.int(value) },
)

const active = ref<number | null>(null)

const peak = computed(() => Math.max(0, ...props.items.map((i) => i.value)))
const peakIndex = computed(() => props.items.findIndex((i) => i.value === peak.value))
const total = computed(() => props.items.reduce((sum, i) => sum + i.value, 0))
const cursor = computed(() => (active.value != null ? active.value : peakIndex.value))
const current = computed<MonthPoint | null>(() => props.items[cursor.value] ?? null)
const empty = computed(() => !props.items.length || peak.value <= 0)

/** Подписи годов под осью: первый месяц ряда и каждый январь. */
const years = computed(() =>
  props.items
    .map((item, index) => ({ item, index }))
    .filter(({ item, index }) => index === 0 || item.month.endsWith('-01'))
    .map(({ item, index }) => ({ label: item.month.slice(0, 4), index })),
)

function heightOf(value: number): string {
  if (peak.value <= 0) return '2px'
  return value > 0 ? `${Math.max(8, (value / peak.value) * 100)}%` : '2px'
}

function onMove(event: PointerEvent) {
  const track = event.currentTarget as HTMLElement
  const rect = track.getBoundingClientRect()
  if (!rect.width || !props.items.length) return
  const index = Math.floor(((event.clientX - rect.left) / rect.width) * props.items.length)
  active.value = Math.min(Math.max(index, 0), props.items.length - 1)
}

function onKey(event: KeyboardEvent) {
  const last = props.items.length - 1
  if (last < 0) return
  const from = cursor.value < 0 ? 0 : cursor.value
  const next = { ArrowLeft: from - 1, ArrowRight: from + 1, Home: 0, End: last }[event.key]
  if (next == null) return
  event.preventDefault()
  active.value = Math.min(Math.max(next, 0), last)
}
</script>

<template>
  <div class="rounded-[20px] bg-surface-2 px-3.5 pb-3 pt-2.5">
    <div class="flex items-baseline justify-between gap-2">
      <span v-tip="props.hint" class="text-[11px] leading-tight text-muted-foreground">{{ props.title }}</span>
      <span v-if="!empty" class="shrink-0 text-[11px] text-muted-foreground">
        всего <span class="tabular-nums text-foreground">{{ props.format(total) }}</span> {{ props.unit }}
      </span>
    </div>

    <div v-if="empty" class="grid text-[12px] text-muted-foreground" :style="{ height: `${props.height + 26}px`, placeItems: 'center' }">
      За выбранный период данных нет
    </div>

    <template v-else>
      <div class="mt-1 flex items-baseline justify-between gap-2 text-[12px]">
        <span class="truncate font-medium">
          {{ current ? fmt.month(current.month) : '-' }}
          <span v-if="active === null" class="font-normal text-muted-foreground">- пик</span>
        </span>
        <span class="shrink-0 tabular-nums font-semibold" :style="{ color: props.color }">
          {{ current ? props.format(current.value) : '-' }} <span class="text-[11px] font-normal text-muted-foreground">{{ props.unit }}</span>
        </span>
      </div>

      <div
        class="mt-1.5 flex cursor-crosshair items-end gap-px border-b border-border/70 outline-none"
        :style="{ height: `${props.height}px` }"
        role="img"
        tabindex="0"
        :aria-label="`${props.title}: всего ${props.format(total)} ${props.unit}, пик ${current ? fmt.month(current.month) : ''}`"
        @pointermove="onMove"
        @pointerleave="active = null"
        @keydown="onKey"
        @blur="active = null"
      >
        <div
          v-for="(item, index) in props.items"
          :key="item.month"
          class="min-w-px flex-1 rounded-t-[3px] transition-[height,opacity] duration-500 ease-spring"
          :style="{
            height: heightOf(item.value),
            background: item.value > 0 ? props.color : 'var(--border)',
            opacity: index === cursor ? 1 : active === null ? 0.72 : 0.38,
          }"
        />
      </div>

      <div class="relative mt-1 h-3.5 text-[10px] leading-none text-muted-foreground">
        <span v-for="year in years" :key="year.index" class="absolute tabular-nums" :style="{ left: `${(year.index / props.items.length) * 100}%` }">{{ year.label }}</span>
      </div>
    </template>
  </div>
</template>
