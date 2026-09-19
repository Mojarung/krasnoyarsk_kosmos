import type { Directive } from 'vue'

const SHOW_DELAY_MS = 350
const GAP_PX = 10
const EDGE_PX = 8

const texts = new WeakMap<HTMLElement, string>()
let bubble: HTMLElement | null = null
let timer: number | undefined
let owner: HTMLElement | null = null
let pending: HTMLElement | null = null
let guarded = false

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
  /*
   * Размер берём из offsetWidth/offsetHeight, а не из getBoundingClientRect:
   * закрытая подсказка уменьшена `scale: .92`, и прямоугольник возвращается
   * уменьшенным — центрирование считалось по чужой ширине и уезжало.
   */
  const width = tip.offsetWidth
  const height = tip.offsetHeight

  const above = rect.top - height - GAP_PX
  const fitsAbove = above >= EDGE_PX
  const top = fitsAbove ? above : rect.bottom + GAP_PX

  const maxLeft = Math.max(EDGE_PX, window.innerWidth - width - EDGE_PX)
  let left = Math.min(Math.max(rect.left + rect.width / 2 - width / 2, EDGE_PX), maxLeft)

  /*
   * У элемента в самом углу центрирование упирается в край экрана, и подсказка
   * уезжает в сторону настолько, что перестаёт пересекаться со своим элементом —
   * выглядит как оторванная плашка над чужим контролом. Тогда прижимаем её к
   * ближнему краю элемента, чтобы связь читалась.
   */
  if (left + width < rect.right) left = Math.min(Math.max(rect.right - width, EDGE_PX), maxLeft)
  else if (left > rect.left) left = Math.min(Math.max(rect.left, EDGE_PX), maxLeft)

  tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`
  tip.dataset.side = fitsAbove ? 'top' : 'bottom'
}

function show(target: HTMLElement) {
  pending = null
  const text = texts.get(target)
  if (!text || !target.isConnected) return
  const tip = ensureBubble()
  owner = target
  tip.textContent = text
  place(target)
  tip.dataset.open = 'true'
}

function hide() {
  window.clearTimeout(timer)
  owner = null
  pending = null
  if (bubble) bubble.dataset.open = 'false'
}

function onEnter(event: Event) {
  const target = event.currentTarget as HTMLElement
  window.clearTimeout(timer)
  pending = target
  timer = window.setTimeout(() => show(target), SHOW_DELAY_MS)
}

/** Страховка: подсказка не должна пережить клик, прокрутку, Escape или уход со вкладки. */
function installGuards() {
  if (guarded) return
  guarded = true
  for (const name of ['pointerdown', 'wheel', 'keydown', 'blur'] as const) window.addEventListener(name, hide, { capture: true, passive: true })
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
    installGuards()
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
    if (owner === el || pending === el) hide()
  },
}

declare module 'vue' {
  interface GlobalDirectives {
    vTip: typeof vTip
  }
}
