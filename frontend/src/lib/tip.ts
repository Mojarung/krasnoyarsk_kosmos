import type { Directive } from 'vue'

const SHOW_DELAY_MS = 350
/** Подсказка переживает короткий уход курсора: рука дрожит, элементы мелкие. */
const HIDE_DELAY_MS = 140
/** Сразу после закрытой подсказки соседняя открывается без паузы — как и переход между элементами. */
const SKIP_DELAY_MS = 500
const GAP_PX = 10
const EDGE_PX = 8

const texts = new WeakMap<HTMLElement, string>()
let bubble: HTMLElement | null = null
let showTimer: number | undefined
let hideTimer: number | undefined
let owner: HTMLElement | null = null
let pending: HTMLElement | null = null
let closedAt = 0
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
   * закрытая подсказка уменьшена, и прямоугольник возвращается уменьшенным —
   * центрирование считалось по чужой ширине и уезжало.
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

  tip.style.left = `${Math.round(left)}px`
  tip.style.top = `${Math.round(top)}px`
  tip.dataset.side = fitsAbove ? 'top' : 'bottom'
}

function show(target: HTMLElement) {
  pending = null
  const text = texts.get(target)
  if (!text || !target.isConnected) {
    hide()
    return
  }
  const tip = ensureBubble()
  owner = target
  tip.textContent = text
  place(target)
  tip.dataset.open = 'true'
}

function hide() {
  window.clearTimeout(showTimer)
  window.clearTimeout(hideTimer)
  if (owner) closedAt = performance.now()
  owner = null
  pending = null
  if (bubble) bubble.dataset.open = 'false'
}

function onEnter(event: Event) {
  const target = event.currentTarget as HTMLElement
  window.clearTimeout(hideTimer)
  if (owner === target) {
    pending = null
    return
  }
  window.clearTimeout(showTimer)
  pending = target
  // Первая подсказка ждёт паузу, чтобы не мельтешить под курсором. Дальше по
  // ряду элементов она ходит сразу: пауза на каждом читается как «потерялась».
  if (owner || performance.now() - closedAt < SKIP_DELAY_MS) show(target)
  else showTimer = window.setTimeout(() => show(target), SHOW_DELAY_MS)
}

/** Клавиатуре подсказка нужна сразу, а после клика мышью — нет: человек уже нажал. */
function onFocus(event: Event) {
  const target = event.currentTarget as HTMLElement
  if (target.matches(':focus-visible')) show(target)
}

function onLeave() {
  window.clearTimeout(showTimer)
  pending = null
  if (!owner) return
  window.clearTimeout(hideTimer)
  hideTimer = window.setTimeout(hide, HIDE_DELAY_MS)
}

/** Страховка: подсказка не должна пережить клик, прокрутку, Escape или уход со вкладки. */
function installGuards() {
  if (guarded) return
  guarded = true
  for (const name of ['pointerdown', 'wheel', 'keydown', 'blur'] as const) window.addEventListener(name, hide, { capture: true, passive: true })
}

const EVENTS: [string, (event: Event) => void][] = [
  ['pointerenter', onEnter],
  ['focus', onFocus],
  ['pointerleave', onLeave],
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
