<script setup lang="ts">
import { ArrowLeft, Car, Crosshair, MapPin, X } from '@lucide/vue'
import { onKeyStroke } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { coordinateLabel, PURPOSES, type Coordinates } from '@/lib/inspections'
import { useInspectionStore } from '@/stores/inspection'
import InspectionCard from './InspectionCard.vue'

const draft = useInspectionStore()
const step = ref(1)
const saving = ref(false)
const error = ref('')
const confirmClose = ref(false)
const latitude = ref(''), longitude = ref('')
const manualKind = ref<'site' | 'access'>('site')
const hasChanges = computed(() => !!draft.site || !!draft.access || !!draft.note)
watch([() => draft.site, () => draft.access], () => { error.value = '' })
watch(step, value => { if (value === 1) manualKind.value = 'site' })
function requestClose() {
  if (saving.value) return
  if (!draft.saved && hasChanges.value) confirmClose.value = true
  else draft.close()
}
onKeyStroke('Escape', (e) => {
  e.preventDefault(); e.stopImmediatePropagation()
  if (draft.picking) draft.picking = null
  else requestClose()
})
function coordinates() {
  const lat = Number(latitude.value.replace(',', '.')), lon = Number(longitude.value.replace(',', '.'))
  if (!latitude.value.trim() || !longitude.value.trim() || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 85 || Math.abs(lon) > 180) {
    error.value = 'Укажите широту от −85 до 85 и долготу от −180 до 180.'; return
  }
  const point: Coordinates = [lon, lat]
  if (manualKind.value === 'site') draft.site = point
  else draft.access = point
  draft.picking = null; error.value = ''
}
async function save() {
  if (!draft.event || !draft.site || saving.value) return
  saving.value = true; error.value = ''; draft.picking = null
  try {
    draft.saved = await api.createInspection({ id: draft.requestId, event_id: draft.event.id, purpose: draft.purpose, note: draft.note.trim(), site: draft.site, access: draft.access })
  } catch (e) { error.value = e instanceof Error ? e.message : 'Не удалось сохранить. Попробуйте ещё раз.' }
  finally { saving.value = false }
}
</script>

<template>
  <section class="panel flex max-h-full w-[440px] max-w-full flex-col !bg-surface-1" aria-label="Планирование осмотра" :aria-busy="saving">
    <header class="flex shrink-0 items-center gap-2 px-4 py-3">
      <Button v-if="step === 2 && !draft.saved" variant="ghost" size="icon-sm" aria-label="Назад к месту осмотра" :disabled="saving" @click="step = 1; draft.picking = null"><ArrowLeft /></Button>
      <h2 class="min-w-0 flex-1 text-base font-semibold">{{ draft.saved ? 'Карточка осмотра' : 'Запланировать осмотр' }}</h2>
      <Button variant="ghost" size="icon-sm" aria-label="Закрыть планирование" :disabled="saving" @click="requestClose"><X /></Button>
    </header>
    <div class="thin-scroll min-h-0 overflow-y-auto overscroll-contain px-5 pb-5">
      <div v-if="confirmClose" class="mb-4 rounded-2xl border bg-surface-2 p-3" role="alert">
        <p class="text-sm">Выйти без сохранения задания?</p>
        <div class="mt-3 flex gap-2"><Button size="sm" variant="secondary" @click="confirmClose = false">Продолжить</Button><Button size="sm" variant="ghost" @click="draft.close()">Выйти без сохранения</Button></div>
      </div>
      <InspectionCard v-if="draft.saved" :task="draft.saved" />
      <template v-else>
        <ol class="mb-5 flex gap-3 text-xs text-muted-foreground" aria-label="Шаги осмотра">
          <li :class="step === 1 && 'font-semibold text-primary'" :aria-current="step === 1 ? 'step' : undefined">1 · Место</li>
          <li :class="step === 2 && 'font-semibold text-primary'" :aria-current="step === 2 ? 'step' : undefined">2 · Задача</li>
          <li>3 · Передача</li>
        </ol>
        <div v-if="step === 1" class="space-y-4">
          <h3 class="text-lg font-semibold">Место осмотра</h3>
          <Button class="w-full" variant="secondary" @click="draft.picking = 'site'"><MapPin />{{ draft.site ? 'Переставить место осмотра' : 'Выбрать место на карте' }}</Button>
          <p v-if="draft.site" class="rounded-xl bg-surface-2 p-3 text-sm" role="status">1 · Место выбрано<br><span class="font-mono text-xs text-muted-foreground">{{ coordinateLabel(draft.site) }}</span></p>
        </div>
        <div v-else class="space-y-4">
          <div><label for="inspection-purpose" class="mb-2 block text-sm font-medium">Цель осмотра</label><select id="inspection-purpose" v-model="draft.purpose" :disabled="saving" class="h-11 w-full rounded-xl border bg-surface-2 px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring"><option v-for="(label, value) in PURPOSES" :key="value" :value="value">{{ label }}</option></select></div>
          <div><label for="inspection-note" class="mb-2 block text-sm font-medium">Что проверить <span class="font-normal text-muted-foreground">· необязательно</span></label><textarea id="inspection-note" v-model="draft.note" :disabled="saving" maxlength="1000" rows="3" placeholder="Например: проверить живую растительность вдоль лесополосы" class="w-full resize-y rounded-xl border bg-surface-2 p-3 text-sm focus-visible:ring-2 focus-visible:ring-ring" /><div class="text-right text-[11px] text-muted-foreground">{{ draft.note.length }} / 1000</div></div>
          <div class="rounded-[20px] border border-border/60 p-4">
            <h3 class="flex items-center gap-2 text-sm font-semibold"><Car class="size-4" />Место остановки <span class="font-normal text-muted-foreground">· необязательно</span></h3>
            <p class="mt-2 text-xs text-muted-foreground">Проходимость и безопасность не проверены.</p>
            <Button class="mt-3" variant="secondary" size="sm" :disabled="saving" @click="draft.picking = 'access'"><Crosshair />{{ draft.access ? 'Переставить точку' : 'Выбрать место остановки' }}</Button>
            <p v-if="draft.access" class="mt-2 font-mono text-xs">2 · {{ coordinateLabel(draft.access) }}</p>
            <Button v-if="draft.access" variant="ghost" size="sm" :disabled="saving" @click="draft.access = null">Убрать точку</Button>
          </div>
        </div>
        <details class="mt-4 text-xs text-muted-foreground">
          <summary class="cursor-pointer rounded focus-visible:ring-2 focus-visible:ring-ring">Ввести координаты вручную</summary>
          <div class="mt-3 space-y-2">
            <label class="block">Для какой точки<select v-model="manualKind" class="mt-1 h-10 w-full rounded-lg border bg-surface-2 px-2"><option value="site">Место осмотра</option><option v-if="step === 2" value="access">Место остановки</option></select></label>
            <div class="grid grid-cols-2 gap-2"><label>Широта<input v-model="latitude" inputmode="decimal" class="mt-1 h-10 w-full rounded-lg border bg-surface-2 px-2" /></label><label>Долгота<input v-model="longitude" inputmode="decimal" class="mt-1 h-10 w-full rounded-lg border bg-surface-2 px-2" /></label></div>
            <Button variant="secondary" size="sm" :disabled="saving" @click="coordinates">Применить координаты</Button>
          </div>
        </details>
        <p v-if="error" class="mt-4 rounded-xl bg-destructive/10 p-3 text-sm text-destructive" role="alert">{{ error }}</p>
        <Button v-if="step === 1" class="mt-5 w-full" :disabled="!draft.site" @click="step = 2; draft.picking = null">Далее</Button>
        <Button v-else class="mt-5 w-full" :disabled="saving || !draft.site" @click="save">{{ saving ? 'Сохраняем…' : 'Сохранить задание' }}</Button>
      </template>
    </div>
  </section>
</template>
