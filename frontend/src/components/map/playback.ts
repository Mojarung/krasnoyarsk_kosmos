import type { ExpressionSpecification, Map as MapLibre } from 'maplibre-gl'
import type { HotspotCollection } from '@/lib/types'

/** Прозрачность, которая гаснет у ещё не наступивших при проигрывании точек. */
export function shownOpacity(value: number): ExpressionSpecification {
  return ['case', ['boolean', ['feature-state', 'hidden'], false], 0, value]
}

/** Толщина кольца пульсации: оно есть только у точек последних дней проигрывания. */
export function recentWidth(value: number): ExpressionSpecification {
  return ['case', ['boolean', ['feature-state', 'recent'], false], value, 0]
}

/**
 * Проигрывание периода через feature-state, а не через фильтр.
 *
 * Смена фильтра заставляет воркер MapLibre заново собрать все тайлы источника. Проигрывание меняло
 * фильтр на каждый день, до 50 раз в секунду, воркер не успевал, и точки появлялись с отставанием.
 * Состояние объекта меняется без пересборки тайлов, а за шаг открываются только точки нового дня.
 */
export class HotspotReveal {
  private order: { id: number; ts: number }[] = []
  private revealed = 0
  private pulsed = 0
  private lastTs: number | null = null

  constructor(
    private readonly map: MapLibre,
    private readonly source: string,
    private readonly pulseWindowS: number,
  ) {}

  setData(collection: HotspotCollection) {
    this.order = collection.features
      .filter((f) => typeof f.id === 'number')
      .map((f) => ({ id: f.id as number, ts: f.properties.ts }))
      .sort((a, b) => a.ts - b.ts)
    // Новые данные пришли посреди проигрывания: состояние строится заново от текущего дня.
    const ts = this.lastTs
    this.reset()
    this.seek(ts)
  }

  seek(ts: number | null) {
    if (ts == null) {
      this.reset()
      return
    }
    if (this.lastTs == null || ts < this.lastTs) this.hideAll()
    this.lastTs = ts
    while (this.revealed < this.order.length && this.order[this.revealed].ts <= ts) {
      this.set(this.order[this.revealed].id, { hidden: false, recent: true })
      this.revealed += 1
    }
    while (this.pulsed < this.revealed && this.order[this.pulsed].ts <= ts - this.pulseWindowS) {
      this.set(this.order[this.pulsed].id, { recent: false })
      this.pulsed += 1
    }
  }

  private hideAll() {
    this.map.removeFeatureState({ source: this.source })
    for (const { id } of this.order) this.set(id, { hidden: true })
    this.revealed = 0
    this.pulsed = 0
  }

  private reset() {
    if (this.lastTs != null) this.map.removeFeatureState({ source: this.source })
    this.lastTs = null
    this.revealed = 0
    this.pulsed = 0
  }

  private set(id: number, state: Record<string, boolean>) {
    this.map.setFeatureState({ source: this.source, id }, state)
  }
}
