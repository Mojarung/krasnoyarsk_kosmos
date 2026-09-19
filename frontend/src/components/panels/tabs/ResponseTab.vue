<script setup lang="ts">
import { Building2, Droplets, MapPinned, Navigation, Siren, Thermometer, Truck, Wind } from '@lucide/vue'
import { computed, onMounted, watch } from 'vue'
import MorphLoader from '@/components/common/MorphLoader.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { fmt, plural } from '@/lib/format'
import type { ResponseCard, ResponseLevel } from '@/lib/types'
import { useQueryStore } from '@/stores/query'
import { type InsightView, useUiStore } from '@/stores/ui'

const emit = defineEmits<{ open: [view: InsightView] }>()
const query = useQueryStore()
const ui = useUiStore()
const plan = computed(() => query.responsePlan)

const LEVELS: { level: ResponseLevel; label: string; color: string }[] = [
  { level: 'critical', label: 'Немедленно', color: 'var(--sev-3)' },
  { level: 'high', label: 'Высокий', color: 'var(--sev-2)' },
  { level: 'medium', label: 'Плановый', color: 'var(--sev-1)' },
  { level: 'low', label: 'Наблюдение', color: 'var(--muted-foreground)' },
]
const LEVEL_COLOR = Object.fromEntries(LEVELS.map((l) => [l.level, l.color])) as Record<ResponseLevel, string>
const OSM_CARDS = 4
const COMPASS = ['С', 'ССВ', 'СВ', 'ВСВ', 'В', 'ВЮВ', 'ЮВ', 'ЮЮВ', 'Ю', 'ЮЮЗ', 'ЮЗ', 'ЗЮЗ', 'З', 'ЗСЗ', 'СЗ', 'ССЗ']
const GROWTH: Record<ResponseCard['growth'], string> = {
  new: 'новый очаг, вчера здесь не горело',
  doubling: 'за сутки вырос вдвое и больше',
  steady: 'держится на уровне вчерашнего',
  fading: 'затухает',
}
const PART_LABELS: Record<string, string> = {
  intensity: 'мощность', size: 'размер', growth: 'рост', weather: 'погода', fuel: 'что горит', exposure: 'сёла рядом',
}

onMounted(() => {
  if (!query.responsePlan) void query.loadResponsePlan()
})
watch(() => query.params, () => void query.loadResponsePlan())

function compass(deg: number): string {
  return COMPASS[Math.round(deg / 22.5) % 16]
}

function showOnMap(card: ResponseCard) {
  ui.responseCardId = card.id
  emit('open', 'overview')
}

function threatened(card: ResponseCard) {
  return (card.threats ?? []).filter((t) => t.horizon_h != null)
}
</script>

<template>
  <div v-if="!plan" class="space-y-3">
    <p class="text-[13px] text-muted-foreground">Собираем план: очаги из базы и ветер из Open-Meteo.</p>
    <div class="grid gap-3 @3xl:grid-cols-2"><Skeleton v-for="i in 4" :key="i" class="h-[260px] rounded-[24px]" /></div>
  </div>

  <div v-else-if="!plan.cards.length" class="rounded-[24px] bg-surface-2 px-5 py-6 text-sm text-muted-foreground">
    За выбранный период в области нет природных термоточек: реагировать не на что.
  </div>

  <div v-else class="grid items-start gap-4 @2xl:grid-cols-[minmax(0,1fr)_minmax(0,2.4fr)]">
    <aside class="space-y-3 @2xl:sticky @2xl:top-0">
      <div class="rounded-[24px] bg-primary-container px-5 py-4 text-on-primary-container">
        <div class="label-caps !text-current opacity-70">Свежие очаги</div>
        <div class="mt-0.5 flex items-baseline gap-2">
          <span class="display-number text-[34px]">{{ fmt.int(plan.fires_total) }}</span>
          <span class="text-xs leading-snug opacity-80">за {{ plural(plan.window.days, ['день', 'дня', 'дней']) }} до {{ plan.window.to ? fmt.date(plan.window.to).replace(/\s*г\.$/, '') : '-' }}</span>
        </div>
        <p class="mt-1.5 text-xs leading-snug opacity-75">План считается по {{ plural(plan.cards.length, ['самому опасному очагу', 'самым опасным очагам', 'самым опасным очагам']) }}. В архивном запросе «свежие» - последние дни периода, когда спутник видел горение.</p>
      </div>
      <div class="grid grid-cols-2 gap-1.5">
        <div v-for="item in LEVELS" :key="item.level" class="rounded-[18px] bg-surface-2 px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[11px] text-muted-foreground"><i class="size-2 rounded-full" :style="{ background: item.color }" />{{ item.label }}</div>
          <div class="mt-0.5 text-xl font-semibold tabular-nums">{{ plan.by_level[item.level] }}</div>
        </div>
      </div>
      <p v-if="plan.external.osm === 'pending'" class="flex items-center gap-2.5 rounded-2xl bg-surface-2 px-3.5 py-2.5 text-xs leading-snug text-muted-foreground"><MorphLoader :size="18" class="shrink-0" />Запрашиваем у OpenStreetMap сёла, дороги и пожарные части. Карточки дополнятся сами, обычно за минуту.</p>
      <p v-else-if="plan.external.osm === 'failed'" class="rounded-2xl bg-destructive/15 px-3.5 py-2.5 text-xs leading-snug text-destructive">OpenStreetMap не ответил по части очагов: сёл под угрозой, дорог и пожарных частей в их карточках нет, приоритет посчитан без них. Повторный запрос уйдёт через три минуты.</p>
      <p v-if="!plan.external.wind" class="rounded-2xl bg-destructive/15 px-3.5 py-2.5 text-xs leading-snug text-destructive">Open-Meteo не ответил: направление ветра неизвестно, прогноз фронта на карте не строится.</p>
      <p class="text-[11px] leading-snug text-muted-foreground">{{ plan.disclaimer }}</p>
      <p class="text-[11px] leading-snug text-muted-foreground/80">{{ plan.sources }}</p>
    </aside>

    <div class="grid gap-3 @4xl:grid-cols-2">
      <article v-for="(card, index) in plan.cards" :key="card.id" class="flex flex-col rounded-[24px] bg-surface-2 p-4" :class="ui.responseCardId === card.id && 'ring-2 ring-primary/70'">
        <header class="flex items-start gap-3">
          <span v-tip="Object.entries(card.priority.parts).map(([k, v]) => `${PART_LABELS[k] ?? k} ${fmt.num(v)}`).join(' · ')" class="flex size-12 shrink-0 flex-col items-center justify-center rounded-2xl text-[#1a0f08]" :style="{ background: LEVEL_COLOR[card.priority.level] }">
            <span class="text-lg font-bold leading-none tabular-nums">{{ Math.round(card.priority.score) }}</span>
            <span class="text-[9px] uppercase tracking-wide opacity-70">из 100</span>
          </span>
          <div class="min-w-0 flex-1">
            <h3 class="text-sm font-semibold leading-tight">№{{ index + 1 }} · {{ card.priority.label }}</h3>
            <p class="mt-0.5 text-xs text-muted-foreground">{{ card.landcover_label }} · {{ fmt.dateTimeUtc(card.last_seen) }}{{ card.is_night ? ' · ночь' : '' }}</p>
            <p class="mt-0.5 text-xs text-muted-foreground">{{ plural(card.hotspots, ['термоточка', 'термоточки', 'термоточек']) }}<template v-if="card.frp_mw != null"> · {{ fmt.num(card.frp_mw) }} МВт</template> · {{ GROWTH[card.growth] }}</p>
          </div>
        </header>

        <div class="mt-3 flex flex-wrap gap-1.5 text-xs">
          <span v-if="card.weather.wind_ms != null" class="flex items-center gap-1.5 rounded-full bg-surface-3 px-2.5 py-1"><Wind class="size-3.5 text-primary" />{{ fmt.num(card.weather.wind_ms) }} м/с<template v-if="card.weather.wind_dir_deg != null">, с {{ compass(card.weather.wind_dir_deg) }}</template></span>
          <span v-if="card.weather.rh2m != null" class="flex items-center gap-1.5 rounded-full bg-surface-3 px-2.5 py-1"><Droplets class="size-3.5 text-primary" />{{ card.weather.rh2m }}%</span>
          <span v-if="card.weather.t2m_c != null" class="flex items-center gap-1.5 rounded-full bg-surface-3 px-2.5 py-1"><Thermometer class="size-3.5 text-primary" />{{ fmt.num(card.weather.t2m_c) }} °C</span>
        </div>

        <section v-if="card.spread.rate_kmh != null" class="mt-3 rounded-[18px] bg-surface-3 px-3.5 py-2.5">
          <div class="flex items-center gap-2 text-[13px]">
            <Navigation v-if="card.spread.heading_deg != null" class="size-4 shrink-0 text-primary transition-transform duration-500" :style="{ transform: `rotate(${card.spread.heading_deg - 45}deg)` }" />
            <span>Фронт до <b class="tabular-nums">{{ fmt.num(card.spread.rate_kmh) }} км/ч</b><template v-if="card.spread.heading_deg != null"> на {{ compass(card.spread.heading_deg) }}</template></span>
          </div>
          <div v-if="card.spread.ellipses.length" class="mt-1.5 grid grid-cols-3 gap-1.5 text-xs text-muted-foreground">
            <span v-for="e in card.spread.ellipses" :key="e.hours">за {{ e.hours }} ч <b class="text-foreground tabular-nums">{{ fmt.num(e.head_km) }} км</b></span>
          </div>
        </section>

        <p v-if="!card.threats && index >= OSM_CARDS" class="mt-3 text-xs text-muted-foreground">Окружение по OpenStreetMap считаем только для {{ OSM_CARDS }} самых опасных очагов.</p>
        <ul v-if="card.threats" class="mt-3 space-y-1 text-xs">
          <li v-for="threat in threatened(card).slice(0, 3)" :key="threat.name" class="flex items-center gap-2 text-destructive"><Siren class="size-3.5 shrink-0" /><span class="min-w-0 flex-1 truncate">{{ threat.name }}</span><span class="shrink-0 tabular-nums">{{ fmt.num(threat.distance_km) }} км · до {{ threat.horizon_h }} ч</span></li>
          <li v-if="!threatened(card).length" class="flex items-center gap-2 text-muted-foreground"><Building2 class="size-3.5 shrink-0" />На пути фронта в ближайшие 6 часов населённых пунктов нет</li>
          <li v-if="card.arrival" class="flex items-center gap-2 text-muted-foreground"><Truck class="size-3.5 shrink-0" /><span class="min-w-0 flex-1 truncate">{{ card.arrival.station }}</span><span class="shrink-0 tabular-nums">{{ fmt.num(card.arrival.distance_km) }} км · около {{ card.arrival.eta_min }} мин</span></li>
        </ul>

        <section class="mt-3 border-t border-border/60 pt-3">
          <div class="text-[13px] font-medium">{{ card.method.label }}</div>
          <ol class="mt-1.5 list-decimal space-y-1 pl-4 text-xs leading-snug text-muted-foreground marker:text-primary">
            <li v-for="step in card.steps" :key="step">{{ step }}</li>
          </ol>
          <div class="mt-2 flex flex-wrap gap-1">
            <span v-for="resource in card.method.resources" :key="resource" class="rounded-full border border-border/70 px-2 py-0.5 text-[11px]">{{ resource }}</span>
          </div>
        </section>

        <Button v-tip="'Свернуть панель и показать на карте эллипсы возможного выгорания на 1, 3 и 6 часов'" variant="secondary" size="sm" class="mt-3 self-start" @click="showOnMap(card)"><MapPinned />Прогноз на карте</Button>
      </article>
    </div>
  </div>
</template>
