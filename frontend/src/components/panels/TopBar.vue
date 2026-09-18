<script setup lang="ts">
import { Bell, BookOpen, Flame, Moon, Sun, Trash2, Workflow } from '@lucide/vue'
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { api } from '@/lib/api'
import { fmt } from '@/lib/format'
import { useLiveStore } from '@/stores/live'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import AgentBar from './AgentBar.vue'

const ui = useUiStore()
const live = useLiveStore()
const query = useQueryStore()

const data = computed(() => query.meta?.data)

async function removeZone(id: number) {
  await api.deleteZone(id)
  await live.loadZones()
}
</script>

<template>
  <TooltipProvider :delay-duration="250">
    <header class="flex items-start gap-3">
      <div class="panel flex h-12 shrink-0 items-center gap-2.5 !rounded-full pl-2 pr-5">
        <span class="grid size-8 place-items-center rounded-full bg-primary text-primary-foreground"><Flame class="size-4" /></span>
        <div class="leading-none">
          <div class="text-sm font-semibold tracking-tight">Зарево</div>
          <div class="mt-0.5 hidden text-[10px] text-muted-foreground sm:block">
            <template v-if="data">{{ data.af_scenes + data.bs_scenes }} сцен · {{ fmt.compact(data.hotspots) }} термоточек</template>
            <template v-else>мониторинг природных пожаров</template>
          </div>
        </div>
      </div>

      <div class="flex min-w-0 flex-1 justify-center"><AgentBar /></div>

      <div class="panel flex h-12 shrink-0 items-center gap-0.5 !rounded-full px-1.5">
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="sm" class="relative gap-2" @click="ui.pipelineOpen = true">
              <Workflow :class="{ 'animate-pulse text-primary': live.pending > 0 }" />
              <span class="hidden tabular-nums md:inline">{{ live.pending > 0 ? `в работе ${live.pending}` : 'Конвейер' }}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>Загрузка чипов и живой ход обработки</TooltipContent>
        </Tooltip>

        <Popover @update:open="(open: boolean) => open && live.markRead()">
          <PopoverTrigger as-child>
            <Button variant="ghost" size="icon" class="relative" aria-label="Алерты по зонам наблюдения">
              <Bell />
              <span v-if="live.unread" class="absolute right-1 top-1 grid min-w-4 place-items-center rounded-full bg-fire px-1 text-[10px] font-semibold leading-4 text-white">{{ live.unread }}</span>
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" class="w-80 rounded-[24px] border-border bg-popover p-4">
            <div class="label-caps mb-2">Зоны наблюдения</div>
            <p v-if="!live.zones.length" class="text-xs text-muted-foreground">Зон пока нет. Создайте зону из текущего запроса в панели слева.</p>
            <div v-for="zone in live.zones" :key="zone.id" class="mb-1 flex items-center justify-between rounded-full bg-surface-3 py-1 pl-3.5 pr-1 text-[13px]">
              <span class="truncate">{{ zone.name }}</span>
              <Button variant="ghost" size="icon-xs" :aria-label="`Удалить зону ${zone.name}`" @click="removeZone(zone.id)"><Trash2 /></Button>
            </div>
            <div class="label-caps mb-2 mt-3">Алерты</div>
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

        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon" as="a" href="/docs" target="_blank" rel="noopener noreferrer" aria-label="Документация REST API"><BookOpen /></Button>
          </TooltipTrigger>
          <TooltipContent>REST API и OGC API Features</TooltipContent>
        </Tooltip>

        <Button variant="ghost" size="icon" aria-label="Сменить тему" @click="ui.toggleTheme"><component :is="ui.theme === 'dark' ? Sun : Moon" /></Button>
      </div>
    </header>
  </TooltipProvider>
</template>
