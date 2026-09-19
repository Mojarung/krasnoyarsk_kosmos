import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import type { FireEventDetail } from '@/lib/types'
import { inspectionId, type Coordinates, type Inspection, type Purpose } from '@/lib/inspections'

export const useInspectionStore = defineStore('inspection', () => {
  const event = shallowRef<FireEventDetail | null>(null)
  const picking = ref<'site' | 'access' | null>(null)
  const site = shallowRef<Coordinates | null>(null)
  const access = shallowRef<Coordinates | null>(null)
  const purpose = ref<Purpose>('damage')
  const note = ref('')
  const saved = shallowRef<Inspection | null>(null)
  const requestId = ref('')
  function start(value: FireEventDetail, task: Inspection | null = null) {
    event.value = value
    saved.value = task
    site.value = task?.site ?? null
    access.value = task?.access ?? null
    purpose.value = task?.purpose ?? 'damage'
    note.value = task?.note ?? ''
    requestId.value = inspectionId()
    picking.value = null
  }
  function pick(point: Coordinates) {
    if (picking.value === 'site') site.value = point
    if (picking.value === 'access') access.value = point
    picking.value = null
  }
  function close() {
    event.value = null
    picking.value = null
    site.value = access.value = null
    saved.value = null
  }
  return { event, picking, site, access, purpose, note, saved, requestId, start, pick, close }
})
