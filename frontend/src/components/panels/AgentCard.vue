<script setup lang="ts">
import { Columns2, Crosshair, Info } from '@lucide/vue'
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import type { AgentCardData } from '@/lib/api'
import { fmt } from '@/lib/format'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ card: AgentCardData }>()
const ui = useUiStore()

const COLORS = { 1: 'var(--sev-1)', 2: 'var(--sev-2)', 3: 'var(--sev-3)' } as const
const total = computed(() => props.card.severity.reduce((sum, item) => sum + item.area_ha, 0))

function show() {
  const top = props.card.largest
  if (top) ui.flyTarget = { lon: top.lon, lat: top.lat, zoom: 11 }
}

function compare() {
  if (props.card.largest) ui.compareSceneId = props.card.largest.scene_id
}
</script>

<template>
  <div class="mt-3 space-y-3 border-t border-border/60 pt-3">
    <div class="flex flex-wrap items-center gap-1.5 text-xs">
      <span class="rounded-full bg-primary-container px-2.5 py-1 font-medium text-on-primary-container">{{ props.card.title }}</span>
      <span class="rounded-full bg-surface-3 px-2.5 py-1 tabular-nums text-muted-foreground">{{ fmt.date(props.card.date_from) }} - {{ fmt.date(props.card.date_to) }}</span>
    </div>

    <p v-for="note in props.card.notes" :key="note" class="flex items-center gap-1.5 text-xs text-muted-foreground"><Info class="size-3.5 shrink-0" />{{ note }}</p>

    <template v-if="!props.card.empty">
      <div class="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        <div v-for="kpi in props.card.kpis" :key="kpi.label" class="rounded-2xl bg-surface-2 px-3 py-2">
          <div class="truncate text-[11px] text-muted-foreground">{{ kpi.label }}</div>
          <div class="mt-0.5 text-base font-semibold leading-tight tabular-nums">{{ fmt.ha(kpi.value) }}<span v-if="kpi.unit" class="ml-1 text-xs font-normal text-muted-foreground">{{ kpi.unit }}</span></div>
          <div class="truncate text-[11px] text-muted-foreground">{{ kpi.sub }}</div>
        </div>
      </div>

      <div v-if="total > 0">
        <div class="flex h-2 gap-0.5 overflow-hidden rounded-full bg-surface-3">
          <div v-for="item in props.card.severity" :key="item.severity" class="h-full rounded-full" :style="{ flexGrow: Math.max(item.share, 0.004), flexBasis: 0, background: COLORS[item.severity] }" />
        </div>
        <div class="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
          <span v-for="item in props.card.severity" :key="item.severity" class="flex items-center gap-1.5">
            <i class="size-1.5 rounded-full" :style="{ background: COLORS[item.severity] }" />{{ item.label }} {{ fmt.pct(item.share) }}
          </span>
        </div>
      </div>

      <div v-if="props.card.largest" class="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-surface-2 px-3 py-2">
        <div class="text-[13px]">
          <span class="text-muted-foreground">Крупнейшая гарь</span>
          <span class="ml-2 font-semibold tabular-nums">{{ fmt.ha(props.card.largest.area_ha) }} га</span>
          <span class="ml-2 text-xs text-muted-foreground">{{ fmt.date(props.card.largest.date_post) }}</span>
        </div>
        <div class="flex gap-1">
          <Button v-tip="'Перелететь к этой гари на карте'" size="xs" variant="tonal" @click="show"><Crosshair />Показать</Button>
          <Button v-tip="'Открыть сравнение снимков до и после пожара'" size="xs" variant="secondary" @click="compare"><Columns2 />До и после</Button>
        </div>
      </div>
    </template>
  </div>
</template>
