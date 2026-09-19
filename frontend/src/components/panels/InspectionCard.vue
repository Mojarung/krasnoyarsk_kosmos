<script setup lang="ts">
import { Check, Copy, ExternalLink, Link, Route } from '@lucide/vue'
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { coordinateLabel, inspectionText, inspectionMapUrl, inspectionCardUrl, PURPOSES, routeUrl, type Inspection } from '@/lib/inspections'
import { fmt } from '@/lib/format'
import { yandexMapsUrl } from '@/lib/yandex-maps'

const props = defineProps<{ task: Inspection; shared?: boolean }>()
const link = computed(() => inspectionMapUrl(props.task))
const cardLink = computed(() => inspectionCardUrl(props.task.share_token))
const copied = ref('')
const error = ref('')
const manual = ref('')
const siteUrl = computed(() => yandexMapsUrl([...props.task.site, ...props.task.site]))
async function copy(kind: 'link' | 'task' | 'card') {
  error.value = ''; copied.value = ''
  const value = kind === 'card' ? cardLink.value : kind === 'link' ? link.value : inspectionText(props.task)
  try {
    await navigator.clipboard.writeText(value)
    copied.value = kind === 'task' ? 'Задание скопировано' : 'Ссылка скопирована'
    manual.value = ''
  }
  catch { error.value = 'Браузер не разрешил копирование. Выделите текст ниже.'; manual.value = value }
}
</script>

<template>
  <div class="space-y-4" data-testid="inspection-card">
    <div class="rounded-[20px] bg-primary-container/60 p-4">
      <div class="flex items-center gap-2 text-xs font-medium"><Check class="size-4" />{{ shared ? 'Карточка осмотра · только чтение' : 'Задание сохранено' }}</div>
      <h3 class="mt-2 text-lg font-semibold">{{ PURPOSES[task.purpose] }}</h3>
      <p class="mt-1 text-xs text-muted-foreground">{{ task.event_id }} · {{ fmt.date(task.created_at) }}</p>
    </div>
    <p v-if="task.note" class="whitespace-pre-wrap break-words text-sm leading-relaxed">{{ task.note }}</p>
    <dl class="space-y-3 text-sm">
      <div><dt class="font-medium">1 · Место осмотра</dt><dd class="mt-1 font-mono text-xs text-muted-foreground">{{ coordinateLabel(task.site) }}</dd></div>
      <div><dt class="font-medium">2 · Место остановки</dt><dd class="mt-1 text-xs text-muted-foreground">{{ task.access ? coordinateLabel(task.access) : 'Не указано' }}</dd></div>
    </dl>
    <p v-if="task.access" class="text-xs text-muted-foreground">Проходимость и безопасность не проверены.</p>
    <div class="flex flex-wrap gap-2">
      <Button v-if="task.access" as="a" :href="routeUrl(task.access)" target="_blank" rel="noopener noreferrer" size="sm"><Route />Маршрут в Яндекс Картах<ExternalLink class="!size-3" /></Button>
      <Button v-if="siteUrl" as="a" :href="siteUrl" target="_blank" rel="noopener noreferrer" variant="secondary" size="sm">Место на Яндекс Картах</Button>
    </div>
    <div class="border-t pt-4">
      <div class="text-sm font-semibold">Передать специалисту</div>
      <div class="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" @click="copy('card')"><Link />Ссылка на карточку</Button>
        <Button variant="ghost" size="sm" @click="copy('task')"><Copy />Скопировать задание</Button>
        <Button variant="ghost" size="sm" @click="copy('link')">Ссылка на Яндекс Карты</Button>
      </div>
      <p class="sr-only" role="status">{{ copied }}</p>
      <p v-if="error" class="text-xs text-destructive" role="alert">{{ error }}</p>
      <textarea v-if="manual" aria-label="Текст для ручного копирования" :value="manual" readonly rows="5" class="mt-2 w-full rounded-xl border bg-surface-2 p-3 text-xs" @focus="($event.target as HTMLTextAreaElement).select()" />
    </div>
  </div>
</template>
