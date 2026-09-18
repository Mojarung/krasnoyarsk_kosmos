<script setup lang="ts">
import { ArrowUp, Search, X } from '@lucide/vue'
import { onClickOutside } from '@vueuse/core'
import { gsap } from 'gsap'
import { computed, nextTick, ref, watch } from 'vue'
import MorphLoader from '@/components/common/MorphLoader.vue'
import { type AgentAction, type AgentCardData, streamSse } from '@/lib/api'
import { useQueryStore } from '@/stores/query'
import { type InsightView, useUiStore } from '@/stores/ui'
import AgentCard from './AgentCard.vue'

const query = useQueryStore()
const ui = useUiStore()

const SUGGESTIONS = ['Самый крупный пожар в Ростовской области за всё время', 'Гари в Калмыкии за июнь 2019', 'Сколько ложных срабатываний отсеяно в Волгоградской области', 'Что нужно восстанавливать в Астраханской области после 2020 года']
const FOCUS_DELAY_MS = 2600
const TAB_VIEWS: Record<string, InsightView> = { report: 'overview', metrics: 'dynamics', restoration: 'restoration', technogenic: 'alarms' }

const root = ref<HTMLElement | null>(null)
const answerBox = ref<HTMLElement | null>(null)
const input = ref('')
const answer = ref('')
const busy = ref(false)
const open = ref(false)
const mode = ref<string | null>(null)
const card = ref<AgentCardData | null>(null)
const refusalExamples = ref<string[]>([])
let controller: AbortController | null = null

const modeLabel = computed(() => (mode.value === 'llm' ? `${query.meta?.agent.model ?? 'LLM'} · карта и справка уже обновлены` : mode.value === 'rules' ? 'разбор по правилам · карта и справка уже обновлены' : mode.value === 'guard' ? 'вопрос вне темы, карта не менялась' : null))

onClickOutside(root, () => !busy.value && (open.value = false))

watch(open, async (value) => {
  if (!value) return
  await nextTick()
  if (answerBox.value) gsap.fromTo(answerBox.value, { height: 0, opacity: 0 }, { height: 'auto', opacity: 1, duration: 0.5, ease: 'expo.out' })
})

async function ask(text = input.value) {
  const message = text.trim()
  if (!message || busy.value) return
  input.value = message
  controller?.abort()
  controller = new AbortController()
  answer.value = ''
  mode.value = null
  card.value = null
  refusalExamples.value = []
  busy.value = true
  open.value = true
  try {
    for await (const item of streamSse('/api/v1/agent/chat', { message }, controller.signal)) {
      if (item.event === 'token') answer.value += item.data.text
      else if (item.event === 'done') mode.value = item.data.mode
      else if (item.event === 'card') card.value = item.data
      else if (item.event === 'refusal') refusalExamples.value = item.data.examples
      else if (item.event === 'action') applyAction(item.data)
    }
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) answer.value = 'Агент недоступен. Запрос можно задать вручную в панели слева.'
  } finally {
    busy.value = false
  }
}

function applyAction(action: AgentAction) {
  if (action.type === 'set_query') {
    query.apply({ geometry: action.geometry, regionId: action.region_id, from: action.date_from, to: action.date_to })
  } else if (action.type === 'open_tab') {
    ui.insightOpen = true
    ui.insightTab = TAB_VIEWS[action.tab] ?? 'overview'
  } else {
    window.setTimeout(() => (ui.flyTarget = { lon: action.lon, lat: action.lat, zoom: action.zoom }), FOCUS_DELAY_MS)
  }
}

function close() {
  controller?.abort()
  open.value = false
}
</script>

<template>
  <div ref="root" class="relative w-full max-w-[640px]">
    <form class="panel flex h-12 items-center gap-2 !rounded-full pl-4 pr-1.5 transition-shadow duration-300 focus-within:shadow-[0_0_0_2px_var(--ring)]" @submit.prevent="ask()">
      <Search class="size-4 shrink-0 text-muted-foreground" />
      <input
        v-model="input"
        class="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        placeholder="Спросите: гари в Калмыкии за июль 2023"
        aria-label="Запрос агенту"
        @focus="!answer && (open = true)"
      />
      <button
        type="submit"
        class="grid size-9 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-[border-radius,transform,opacity] duration-300 ease-spring active:scale-90 active:rounded-xl disabled:opacity-40"
        :disabled="busy || !input.trim()"
        aria-label="Отправить"
      >
        <ArrowUp class="size-4" />
      </button>
    </form>

    <div v-if="open" ref="answerBox" class="panel absolute inset-x-0 top-14 z-20 overflow-hidden !rounded-[26px]">
      <div class="p-4">
        <div v-if="!answer && !busy" class="space-y-1.5">
          <div class="label-caps mb-2">Примеры</div>
          <button v-for="item in SUGGESTIONS" :key="item" type="button" class="block w-full rounded-full bg-surface-2 px-4 py-2 text-left text-[13px] transition-colors duration-200 hover:bg-surface-3 active:scale-[0.99]" @click="ask(item)">
            {{ item }}
          </button>
        </div>
        <div v-else class="flex gap-3">
          <MorphLoader v-if="busy && !answer" :size="26" />
          <p class="flex-1 text-sm font-medium leading-relaxed whitespace-pre-wrap">{{ answer }}<span v-if="busy" class="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse rounded-full bg-primary" /></p>
          <button type="button" class="self-start text-muted-foreground hover:text-foreground" aria-label="Закрыть ответ" @click="close"><X class="size-4" /></button>
        </div>
        <AgentCard v-if="card" :card="card" />
        <div v-if="refusalExamples.length" class="mt-3 space-y-1.5 border-t border-border/60 pt-3">
          <div class="label-caps mb-1">Попробуйте так</div>
          <button v-for="item in refusalExamples" :key="item" type="button" class="block w-full rounded-full bg-surface-2 px-4 py-2 text-left text-[13px] transition-colors duration-200 hover:bg-surface-3 active:scale-[0.99]" @click="ask(item)">{{ item }}</button>
        </div>
        <div v-if="modeLabel" class="mt-2.5 text-[11px] text-muted-foreground">Ответ: {{ modeLabel }}</div>
      </div>
    </div>
  </div>
</template>
