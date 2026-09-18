import type { Directive } from 'vue'

const SHOW_DELAY_MS = 350
const GAP_PX = 10
const EDGE_PX = 8

const texts = new WeakMap<HTMLElement, string>()
let bubble: HTMLElement | null = null
let timer: number | undefined
let owner: HTMLElement | null = null

function ensureBubble(): HTMLElement {
  if (!bubble) {
    bubble = document.createElement('div')
    bubble.className = 'fw-tip'
    bubble.setAttribute('role', 'tooltip')
    document.body.append(bubble)
  }
  return bubble
}

function place(target: HTMLElement) {
  const tip = ensureBubble()
  const rect = target.getBoundingClientRect()
  const size = tip.getBoundingClientRect()
  const above = rect.top - size.height - GAP_PX
  const top = above >= EDGE_PX ? above : rect.bottom + GAP_PX
  const left = Math.min(Math.max(rect.left + rect.width / 2 - size.width / 2, EDGE_PX), window.innerWidth - size.width - EDGE_PX)
  tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`
  tip.dataset.side = above >= EDGE_PX ? 'top' : 'bottom'
}

function show(target: HTMLElement) {
  const text = texts.get(target)
  if (!text) return
  const tip = ensureBubble()
  owner = target
  tip.textContent = text
  place(target)
  tip.dataset.open = 'true'
}

function hide() {
  window.clearTimeout(timer)
  owner = null
  if (bubble) bubble.dataset.open = 'false'
}

function onEnter(event: Event) {
  const target = event.currentTarget as HTMLElement
  window.clearTimeout(timer)
  timer = window.setTimeout(() => show(target), SHOW_DELAY_MS)
}

const EVENTS: [string, (event: Event) => void][] = [
  ['pointerenter', onEnter],
  ['focus', onEnter],
  ['pointerleave', hide],
  ['blur', hide],
  ['pointerdown', hide],
]

export const vTip: Directive<HTMLElement, string | null | undefined> = {
  mounted(el, binding) {
    if (binding.value) texts.set(el, binding.value)
    for (const [name, handler] of EVENTS) el.addEventListener(name, handler)
  },
  updated(el, binding) {
    if (binding.value) texts.set(el, binding.value)
    else texts.delete(el)
    if (owner === el) show(el)
  },
  unmounted(el) {
    for (const [name, handler] of EVENTS) el.removeEventListener(name, handler)
    if (owner === el) hide()
  },
}

declare module 'vue' {
  interface GlobalDirectives {
    vTip: typeof vTip
  }
}
