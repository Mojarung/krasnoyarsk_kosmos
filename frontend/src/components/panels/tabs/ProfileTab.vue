<script setup lang="ts">
import { CalendarRange, History, Repeat } from '@lucide/vue'
import { computed, onMounted, watch } from 'vue'
import AnimatedNumber from '@/components/common/AnimatedNumber.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { fmt, plural } from '@/lib/format'
import { useQueryStore } from '@/stores/query'

const query = useQueryStore()
const profile = computed(() => query.profile)

onMounted(() => {
  if (!query.profile) void query.loadProfile()
})
watch(() => query.params, () => void query.loadProfile())

const peakArea = computed(() => Math.max(1, ...(profile.value?.years ?? []).map((y) => y.area_ha)))
const peakSeason = computed(() => Math.max(1, ...(profile.value?.season ?? []).map((m) => m.hotspots)))

function deviationLabel(value: number | null): string {
  if (value == null) return ''
  const sign = value > 0 ? '+' : ''
  return `${sign}${fmt.pct(value)} к среднему`
}
</script>

<template>
  <!-- Профиль грузится дольше справки: он считает по всем годам. Заглушка повторяет раскладку, чтобы содержимое не прыгало. -->
  <div v-if="!profile" class="grid items-start gap-4 @2xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
    <div class="space-y-3">
      <div class="grid grid-cols-2 gap-2 @2xl:grid-cols-1"><Skeleton v-for="i in 2" :key="i" class="h-[92px] rounded-[24px]" /></div>
      <Skeleton class="h-[82px] rounded-[24px]" />
      <Skeleton class="h-[110px] rounded-[24px]" />
    </div>
    <div class="space-y-4">
      <div class="space-y-1.5"><Skeleton v-for="i in 4" :key="i" class="h-[88px] rounded-[20px]" /></div>
      <Skeleton class="h-[124px] rounded-[20px]" />
      <div class="grid gap-1.5 @2xl:grid-cols-2"><Skeleton v-for="i in 2" :key="i" class="h-[46px] rounded-[20px]" /></div>
    </div>
  </div>

  <div v-else class="grid items-start gap-4 @2xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
    <div class="space-y-3">
      <div class="grid grid-cols-2 gap-2 @2xl:grid-cols-1">
        <div v-tip="'Доля территории, которая за все годы наблюдений хотя бы раз попадала под огонь'" class="rounded-[24px] bg-surface-2 px-4 py-3.5">
          <div class="flex items-center gap-1.5 text-[11px] opacity-75"><History class="size-3.5" />Горело хоть раз</div>
          <div class="mt-1 flex items-baseline gap-1.5">
            <AnimatedNumber :value="profile.recurrence.touched_ha" :format="fmt.compact" class="display-number text-[28px]" />
            <span class="text-sm opacity-70">га</span>
          </div>
          <div class="mt-0.5 text-[11px] text-muted-foreground">{{ fmt.pct(profile.recurrence.touched_share) }} территории запроса</div>
        </div>
        <div v-tip="'Ячейки сетки VIIRS 375 м, в которых огонь фиксировался в разные годы. Здесь горит из года в год, а не случайно'" class="rounded-[24px] bg-primary-container px-4 py-3.5 text-on-primary-container">
          <div class="flex items-center gap-1.5 text-[11px] opacity-75"><Repeat class="size-3.5" />Горит повторно</div>
          <div class="mt-1 flex items-baseline gap-1.5">
            <AnimatedNumber :value="profile.recurrence.repeat_ha" :format="fmt.compact" class="display-number text-[28px]" />
            <span class="text-sm opacity-70">га</span>
          </div>
          <div class="mt-0.5 text-[11px] opacity-75">{{ fmt.pct(profile.recurrence.repeat_share) }} горевшей площади</div>
        </div>
      </div>

      <div v-if="profile.fire_season" v-tip="'Самый короткий отрезок месяцев, на который приходится 80% всех термоточек'" class="rounded-[24px] bg-tertiary-container/70 px-4 py-3.5">
        <div class="flex items-center gap-1.5 text-[11px] opacity-75"><CalendarRange class="size-3.5" />Ядро пожарного сезона</div>
        <div class="mt-1 text-[17px] font-medium leading-tight">{{ profile.fire_season.from }} - {{ profile.fire_season.to }}</div>
        <div class="mt-0.5 text-[11px] text-muted-foreground">{{ plural(profile.fire_season.months, ['месяц', 'месяца', 'месяцев']) }}, {{ fmt.pct(profile.fire_season.share) }} термоточек</div>
      </div>

      <div class="space-y-1.5 rounded-[24px] bg-surface-2 px-4 py-3.5 text-[13px]">
        <div class="flex justify-between gap-3"><span class="text-muted-foreground">Наблюдения с</span><span class="tabular-nums">{{ profile.coverage.first_day ? fmt.date(profile.coverage.first_day) : '-' }}</span></div>
        <div class="flex justify-between gap-3"><span class="text-muted-foreground">Лет в базе</span><span class="tabular-nums">{{ profile.coverage.years }}</span></div>
        <div class="flex justify-between gap-3"><span class="text-muted-foreground">Худший год</span><span class="tabular-nums">{{ profile.worst_year ?? '-' }}</span></div>
      </div>
      <p class="text-[11px] leading-snug text-muted-foreground">{{ profile.method }}</p>
    </div>

    <div class="space-y-4">
      <div>
        <div class="label-caps mb-1.5"><span v-tip="'Площадь гарей по годам. Год, попавший в период запроса, выделен'" class="term">Год за годом</span></div>
        <div class="space-y-1.5">
          <div v-for="year in profile.years" :key="year.year" class="rounded-[20px] px-4 py-3" :class="year.in_query ? 'bg-primary-container/60' : 'bg-surface-2'">
            <div class="flex items-start justify-between gap-3">
              <span class="text-[13px] font-medium tabular-nums">{{ year.year }}</span>
              <span class="shrink-0 text-[13px] font-semibold tabular-nums">{{ fmt.ha(year.area_ha) }} га</span>
            </div>
            <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
              <div class="h-full rounded-full bg-primary transition-[width] duration-700 ease-spring" :style="{ width: `${(year.area_ha / peakArea) * 100}%` }" />
            </div>
            <div class="mt-1.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
              <span>{{ plural(year.hotspots, ['термоточка', 'термоточки', 'термоточек']) }}</span>
              <span v-if="year.frp_mw">суммарно {{ fmt.compact(year.frp_mw) }} МВт</span>
              <span v-if="year.area_deviation != null" :class="year.area_deviation > 0 ? 'text-primary' : ''">{{ deviationLabel(year.area_deviation) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div>
        <div class="label-caps mb-1.5"><span v-tip="'Сколько термоточек приходится на каждый месяц за все годы наблюдений'" class="term">Сезонность</span></div>
        <!-- Высота полосы задана явно: проценты столбика считаются от неё, а не от высоты, выведенной флексом. -->
        <div class="flex gap-1 rounded-[20px] bg-surface-2 px-3 py-3">
          <div v-for="month in profile.season" :key="month.month" v-tip="`${month.label}: ${plural(month.hotspots, ['термоточка', 'термоточки', 'термоточек'])}`" class="flex min-w-0 flex-1 flex-col items-center gap-1">
            <div class="flex h-[76px] w-full items-end">
              <div class="w-full rounded-t-sm transition-[height] duration-700 ease-spring" :style="{ height: `${month.hotspots ? Math.max(3, (month.hotspots / peakSeason) * 100) : 2}%`, background: month.hotspots ? 'var(--fire)' : 'var(--surface-3)' }" />
            </div>
            <span class="truncate text-[10px] text-muted-foreground">{{ month.label.slice(0, 3) }}</span>
          </div>
        </div>
      </div>

      <div v-if="profile.recurrence.buckets.length">
        <div class="label-caps mb-1.5"><span v-tip="'Ячейки 375 м по числу разных лет, в которые они горели'" class="term">Повторяемость горимости</span></div>
        <div class="grid gap-1.5 @2xl:grid-cols-2">
          <div v-for="bucket in profile.recurrence.buckets" :key="bucket.years" class="flex items-center justify-between gap-3 rounded-[20px] bg-surface-2 px-4 py-2.5 text-[13px]">
            <span>{{ plural(bucket.years, ['год', 'года', 'лет']) }} с огнём</span>
            <span class="shrink-0 tabular-nums">{{ fmt.ha(bucket.area_ha) }} га · {{ fmt.pct(bucket.share) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
