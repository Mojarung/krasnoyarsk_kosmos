<script setup lang="ts">
import { Check, TriangleAlert } from '@lucide/vue'
import { computed } from 'vue'
import type { JobEvent } from '@/lib/types'

const props = defineProps<{ job: JobEvent; stages: { stage: string; label: string }[] }>()

const steps = computed(() => props.stages.filter((s) => s.stage !== 'queued' && s.stage !== 'done'))
const activeIndex = computed(() => (props.job.status === 'done' ? steps.value.length : steps.value.findIndex((s) => s.stage === props.job.stage)))
</script>

<template>
  <div class="rounded-[20px] bg-surface-2 px-4 py-3">
    <div class="flex items-center justify-between gap-3 text-[13px]">
      <span class="truncate font-medium">{{ props.job.scene_id }}</span>
      <span v-if="props.job.status === 'done'" class="flex items-center gap-1 text-xs text-tertiary"><Check class="size-3.5" />на карте</span>
      <span v-else-if="props.job.status === 'failed'" class="flex items-center gap-1 text-xs text-destructive"><TriangleAlert class="size-3.5" />ошибка</span>
      <span v-else class="text-xs text-muted-foreground">{{ props.job.status === 'queued' ? 'в очереди' : 'в работе' }}</span>
    </div>
    <div class="mt-2.5 flex items-center gap-1">
      <div
        v-for="(step, index) in steps"
        :key="step.stage"
        class="h-1.5 rounded-full transition-[flex-grow,background-color] duration-700 ease-spring"
        :class="[
          index < activeIndex ? 'bg-primary' : index === activeIndex ? 'bg-primary animate-pulse' : 'bg-surface-3',
          props.job.status === 'failed' && index === activeIndex && '!bg-destructive',
        ]"
        :style="{ flexGrow: index === activeIndex ? 3 : 1, flexBasis: 0 }"
      />
    </div>
    <p class="mt-1.5 truncate text-xs text-muted-foreground" :title="props.job.message">{{ props.job.message }}</p>
  </div>
</template>
