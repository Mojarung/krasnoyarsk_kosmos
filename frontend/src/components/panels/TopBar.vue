<script setup lang="ts">
import { Bell, BellPlus, BookOpen, Flame, Moon, Sun, Trash2, Workflow } from '@lucide/vue'
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { api } from '@/lib/api'
import { APP_NAME, APP_TAGLINE } from '@/lib/brand'
import { fmt } from '@/lib/format'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import AgentBar from './AgentBar.vue'

const ui = useUiStore()
const live = useLiveStore()
const query = useQueryStore()

const data = computed(() => query.meta?.data)
const zoneName = ref('')
const saving = ref(false)

async function watchZone() {
  if (!query.geometry) return
  saving.value = true
  try {
    await api.createZone(zoneName.value.trim() || query.regionName, query.geometry, null)
    zoneName.value = ''
    await live.loadZones()
  } finally {
    saving.value = false
  }
}

async function removeZone(id: number) {
  await api.deleteZone(id)
  await live.loadZones()
}
</script>

<template>
  <header class="flex items-start gap-3">
    <div v-tip="'Сервис мониторинга природных пожаров по данным VIIRS и Sentinel'" class="panel pointer-events-auto flex h-12 shrink-0 items-center gap-2.5 !rounded-full pl-2 pr-5">
      <span class="grid size-8 place-items-center rounded-full bg-primary text-primary-foreground"><Flame class="size-4" /></span>
      <div class="leading-none">
        <div class="text-sm font-semibold tracking-tight">{{ APP_NAME }}</div>
        <div class="mt-0.5 hidden text-[10px] text-muted-foreground sm:block">
          <template v-if="data">{{ data.af_scenes + data.bs_scenes }} сцен · {{ fmt.compact(data.hotspots) }} термоточек</template>
          <template v-else>{{ APP_TAGLINE }}</template>
        </div>
      </div>
    </div>

    <div class="flex min-w-0 flex-1 justify-center"><AgentBar class="pointer-events-auto" /></div>

    <div class="panel pointer-events-auto flex h-12 shrink-0 items-center gap-0.5 !rounded-full px-1.5">
      <Button v-tip="'Конвейер: загрузить свой чип и смотреть ход обработки вживую'" variant="ghost" size="sm" class="gap-2" @click="ui.pipelineOpen = true">
        <Workflow :class="{ 'animate-pulse text-primary': live.pending > 0 }" />
        <span class="hidden tabular-nums md:inline">{{ live.pending > 0 ? `в работе ${live.pending}` : 'Конвейер' }}</span>
      </Button>

      <Popover @update:open="(open: boolean) => open && live.markRead()">
        <PopoverTrigger as-child>
          <Button v-tip="'Зоны наблюдения и алерты о новых термоточках'" variant="ghost" size="icon" class="relative" aria-label="Зоны наблюдения и алерты">
            <Bell />
            <span v-if="live.unread" class="absolute right-1 top-1 grid min-w-4 place-items-center rounded-full bg-fire px-1 text-[10px] font-semibold leading-4 text-white">{{ live.unread }}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" class="w-80 rounded-[24px] border-border bg-popover p-4">
          <div class="label-caps mb-2">Следить за текущей территорией</div>
          <form class="flex gap-1.5" @submit.prevent="watchZone">
            <input v-model="zoneName" :placeholder="query.regionName" aria-label="Название зоны" class="h-8 min-w-0 flex-1 rounded-full bg-surface-3 px-3.5 text-[13px] outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/50" />
            <Button v-tip="'Новая термоточка пожара в этой зоне придёт алертом сюда. Webhook задаётся через POST /api/v1/zones'" type="submit" size="sm" variant="tonal" :disabled="saving || !query.geometry"><BellPlus />Следить</Button>
          </form>

          <div v-if="live.zones.length" class="mt-3 space-y-1">
            <div v-for="zone in live.zones" :key="zone.id" class="flex items-center justify-between rounded-full bg-surface-3 py-1 pl-3.5 pr-1 text-[13px]">
              <span class="truncate">{{ zone.name }}</span>
              <Button v-tip="'Перестать следить'" variant="ghost" size="icon-xs" :aria-label="`Удалить зону ${zone.name}`" @click="removeZone(zone.id)"><Trash2 /></Button>
            </div>
          </div>

          <div class="label-caps mb-2 mt-4">Алерты</div>
          <p v-if="!live.alerts.length" class="text-xs text-muted-foreground">Новых термоточек в зонах не было.</p>
          <div class="thin-scroll max-h-48 space-y-1 overflow-y-auto">
            <button
              v-for="alert in live.alerts.slice(0, 20)"
              :key="alert.id"
              type="button"
              class="block w-full rounded-2xl bg-surface-3 px-3.5 py-2 text-left text-xs transition-colors hover:bg-accent"
              @click="ui.flyTarget = { lon: alert.lon, lat: alert.lat, zoom: 10 }"
            >
              <span class="font-medium text-fire">{{ alert.n_hotspots }} термоточек</span> · {{ alert.zone_name }}
              <span class="block text-muted-foreground">{{ fmt.dateTimeUtc(alert.acquired_at) }}</span>
            </button>
          </div>
        </PopoverContent>
      </Popover>

      <Button v-tip="'Документация REST API и OGC API Features'" variant="ghost" size="icon" as="a" href="/docs" target="_blank" rel="noopener noreferrer" aria-label="Документация REST API"><BookOpen /></Button>
      <Button v-tip="ui.theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'" variant="ghost" size="icon" aria-label="Сменить тему" @click="ui.toggleTheme"><component :is="ui.theme === 'dark' ? Sun : Moon" /></Button>
    </div>
  </header>
</template>
