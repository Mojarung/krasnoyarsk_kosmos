<script setup lang="ts">
import { defineAsyncComponent, onMounted, ref, shallowRef } from 'vue'
import { api } from '@/lib/api'
import type { Inspection } from '@/lib/inspections'
import InspectionCard from './InspectionCard.vue'
import { Button } from '@/components/ui/button'

const InspectionMap = defineAsyncComponent(() => import('@/components/map/InspectionMap.vue'))
const props = defineProps<{ token: string }>()
const task = shallowRef<Inspection | null>(null)
const error = ref(''), loading = ref(true)
async function load() {
  loading.value = true; error.value = ''
  try { task.value = await api.sharedInspection(props.token) }
  catch (e) { error.value = e instanceof Error ? e.message : 'Не удалось открыть карточку' }
  finally { loading.value = false }
}
onMounted(() => {
  const robots = document.createElement('meta'); robots.name = 'robots'; robots.content = 'noindex, nofollow'; document.head.append(robots)
  const referrer = document.createElement('meta'); referrer.name = 'referrer'; referrer.content = 'no-referrer'; document.head.append(referrer)
  void load()
})
</script>

<template>
  <main class="h-full overflow-y-auto bg-background px-4 py-5 sm:py-10">
    <div class="mx-auto max-w-xl">
      <header class="mb-5 flex items-center justify-between gap-3"><div><p class="text-xs text-muted-foreground">Кордон · обследование территории</p><h1 class="mt-1 text-xl font-semibold">Задание на осмотр</h1></div><a href="/" class="rounded-full bg-secondary px-4 py-2 text-xs focus-visible:ring-2 focus-visible:ring-ring">К карте</a></header>
      <p v-if="loading" class="py-12 text-sm" role="status">Загружаем карточку…</p>
      <div v-else-if="error" role="alert" class="rounded-2xl border p-5"><p class="text-sm">{{ error }}</p><Button class="mt-4" variant="secondary" @click="load">Повторить</Button></div>
      <template v-else-if="task"><InspectionMap :task="task" class="mb-5" /><InspectionCard :task="task" shared /></template>
    </div>
  </main>
</template>
