import type { Map as MapLibre } from 'maplibre-gl'
import { TerraDraw, TerraDrawPolygonMode, TerraDrawRectangleMode } from 'terra-draw'
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter'
import type { AreaGeometry } from '@/lib/types'

const STYLE = {
  fillColor: '#e3b9a4' as const,
  fillOpacity: 0.18,
  outlineColor: '#e3b9a4' as const,
  outlineWidth: 2,
}

export function beginDraw(map: MapLibre, mode: 'polygon' | 'rectangle', onFinish: (geometry: AreaGeometry) => void) {
  const draw = new TerraDraw({
    adapter: new TerraDrawMapLibreGLAdapter({ map }),
    modes: [
      new TerraDrawPolygonMode({ styles: { ...STYLE, closingPointColor: '#f5e0d5', closingPointWidth: 6 } }),
      new TerraDrawRectangleMode({ styles: STYLE }),
    ],
  })
  draw.start()
  draw.setMode(mode)
  draw.on('finish', (id) => {
    const feature = draw.getSnapshot().find((f) => f.id === id)
    if (feature?.geometry.type === 'Polygon') onFinish(feature.geometry as AreaGeometry)
  })
  return {
    stop: () => {
      draw.stop()
    },
  }
}
