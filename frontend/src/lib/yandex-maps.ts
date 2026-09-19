import type { AreaGeometry } from './types'

export type MapBounds = [west: number, south: number, east: number, north: number]

export function territoryBounds(geometry: AreaGeometry | null): MapBounds | null {
  if (!geometry) return null
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity
  for (const polygon of polygons) {
    for (const ring of polygon) {
      for (const [lon, lat] of ring) {
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null
        west = Math.min(west, lon)
        south = Math.min(south, lat)
        east = Math.max(east, lon)
        north = Math.max(north, lat)
      }
    }
  }
  return validBounds([west, south, east, north]) ? [west, south, east, north] : null
}

function validBounds(bounds: MapBounds): boolean {
  const [west, south, east, north] = bounds
  return bounds.every(Number.isFinite) && west >= -180 && east <= 180
    && south >= -90 && north <= 90 && west <= east && south <= north
}

function mercatorY(latitude: number): number {
  const radians = Math.max(-85.051129, Math.min(85.051129, latitude)) * Math.PI / 180
  return Math.log(Math.tan(Math.PI / 4 + radians / 2))
}

/** Show the whole area, not a guessed access point. No route or fire perimeter is sent. */
export function yandexMapsUrl(bounds: MapBounds | null): string | null {
  if (!bounds || !validBounds(bounds)) return null
  const [west, south, east, north] = bounds
  const ySouth = mercatorY(south), yNorth = mercatorY(north)
  const longitude = (west + east) / 2
  const latitude = (2 * Math.atan(Math.exp((ySouth + yNorth) / 2)) - Math.PI / 2) * 180 / Math.PI
  const span = Math.max((east - west) / 360, (yNorth - ySouth) / (2 * Math.PI))
  // Conservative 320px viewport with margin also accommodates a phone or a map sidebar.
  const zoom = span > 0 ? Math.max(1, Math.min(16, Math.floor(Math.log2(320 / (256 * span * 1.25))))) : 16
  const url = new URL('https://yandex.ru/maps/')
  url.searchParams.set('ll', `${longitude.toFixed(6)},${latitude.toFixed(6)}`)
  url.searchParams.set('z', String(zoom))
  url.searchParams.set('l', 'map')
  return url.toString()
}
