import { test, expect, type Page, type APIRequestContext } from '@playwright/test'

async function passport(page: Page, request: APIRequestContext, id = 'bs-FE06923') {
  const event = await (await request.get(`/api/v1/events/${id}`)).json()
  // Restrict only the list to a real fixture; details, imagery, calculations and map remain real.
  await page.route(/\/api\/v1\/events\?/, route => route.fulfill({ json: { items: [event], total: 1, offset: 0, limit: 30 } }))
  await page.goto('/')
  await expect(page.locator('main > .z-50')).toHaveCount(0, { timeout: 60_000 })
  const button = page.getByRole('button', { name: 'Паспорта пожаров', exact: true })
  if (!await button.isVisible()) await page.getByRole('button', { name: /га|Сводка/ }).first().click()
  await button.click()
  await page.getByRole('button', { name: `Открыть паспорт ${id}`, exact: true }).click()
  return event
}

test('real map comparison: dates, keyboard, pan, theme and return', async ({ page, request }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  await passport(page, request)
  await page.getByRole('button', { name: 'После пожара', exact: true }).click()
  const slider = page.getByRole('slider', { name: 'Разделитель снимков' })
  await expect(slider).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(2)
  await slider.focus(); await page.keyboard.press('ArrowRight')
  await expect(slider).toHaveAttribute('aria-valuenow', '55')
  await expect.poll(async () => { const r = (await slider.boundingBox())!; return Math.round((r.x + r.width / 2) / page.viewportSize()!.width * 100) }).toBe(55)
  const handle = (await slider.boundingBox())!
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down(); await page.mouse.move(page.viewportSize()!.width * .65, handle.y + handle.height / 2, { steps: 10 }); await page.mouse.up()
  await expect(slider).toHaveAttribute('aria-valuenow', '65')
  await page.mouse.move(1000, 520); await page.mouse.down(); await page.mouse.move(1100, 570); await page.mouse.up()
  await page.mouse.wheel(0, -180)
  await page.getByRole('button', { name: 'Сменить тему' }).click()
  await expect(slider).toBeVisible()
  await page.screenshot({ path: '/tmp/spatial-compare-light.png' })
  await page.getByRole('button', { name: 'Сменить тему' }).click()
  await page.screenshot({ path: '/tmp/spatial-compare-dark.png' })
  await page.getByRole('button', { name: 'Закрыть режим карты' }).click()
  await expect(page.getByRole('heading', { name: 'Паспорт пожара', exact: true })).toBeVisible()
  await expect(page.locator('.maplibregl-canvas')).toHaveCount(1)
  expect(errors).toEqual([])
})

for (const id of ['bs-FE06923', 'bs-BS_live_ff24d9fb', 'bs-FE08918']) {
  test(`real work polygons, areas and map-to-inspection: ${id}`, async ({ page, request }) => {
    test.setTimeout(180_000)
    await passport(page, request, id)
    await page.getByRole('button', { name: 'Участки работ', exact: true }).click()
    await expect(page.getByLabel('Легенда участков')).toBeVisible({ timeout: 150_000 })
    const data = await (await request.get(`/api/v1/events/${id}/work-map`)).json()
    expect(data.status).toBe('ready')
    expect(data.map.features.length).toBeGreaterThan(0)
    expect(data.map.features.reduce((n: number, f: any) => n + f.properties.area_ha, 0)).toBeCloseTo(data.area_ha, 5)
    expect(data.totals.reduce((n: number, t: any) => n + t.area_ha, 0)).toBeCloseTo(data.area_ha, 5)
    // Click real map polygons using WebMercator camera fit, without mutating application state.
    const viewport = page.viewportSize()!
    const mercator = ([lon, lat]: number[]) => [lon / 360 + .5, .5 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / (2 * Math.PI)]
    const [w,s,e,n] = data.bbox
    const sw = mercator([w,s]), ne = mercator([e,n])
    const scale = Math.min((viewport.width - 90) / (ne[0] - sw[0]), (viewport.height - 280) / (sw[1] - ne[1]), 512 * 2 ** 13)
    const cx = (sw[0] + ne[0]) / 2, cy = (sw[1] + ne[1]) / 2
    for (const f of [...data.map.features].sort((a:any,b:any) => b.properties.area_ha-a.properties.area_ha).slice(0,20)) {
      const ring = f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] : f.geometry.coordinates[0][0]
      const coord = [(ring[0][0]+ring[1][0]+ring[2][0])/3, (ring[0][1]+ring[1][1]+ring[2][1])/3]
      const p = mercator(coord), x = viewport.width/2+(p[0]-cx)*scale, y = (190+viewport.height-90)/2+(p[1]-cy)*scale
      if (x<400 && y<380 || y<200 || y>viewport.height-150) continue
      await page.mouse.click(x,y)
      if (await page.getByRole('button', { name: 'Назначить осмотр', exact: true }).isVisible()) break
    }
    await expect(page.getByLabel('Выбранный участок', { exact: true })).toBeVisible()
    if (id === 'bs-FE08918') {
      await page.setViewportSize({ width: 390, height: 844 })
      await page.getByRole('button', { name: 'Сменить тему' }).click()
      await expect(page.getByLabel('Легенда участков')).toBeInViewport()
      await expect(page.getByRole('button', { name: 'Назначить осмотр', exact: true })).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    }
    await page.screenshot({ path: `/tmp/spatial-works-${id}.png` })
    await page.getByRole('button', { name: 'Назначить осмотр', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('Место выбрано')
    await page.getByRole('button', { name: 'Далее', exact: true }).click()
    await expect(page.getByLabel('Цель осмотра')).toHaveValue('recovery')
    await expect(page.getByRole('heading', { name: 'Участки работ', exact: true })).toHaveCount(0)
  })
}

test('narrow screen and missing imagery do not display a fake comparison', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await passport(page, request)
  await page.route('**/api/v1/events/*/vegetation*', route => route.fulfill({ json: { id: 'test', status: 'partial', recent: { status: 'missing', message: 'Нет пригодного свежего снимка' }, frames: [] } }))
  await page.getByRole('button', { name: 'После пожара', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('Нет пригодного свежего снимка')
  await expect(page.getByRole('slider')).toHaveCount(0)
  await page.getByRole('button', { name: 'Закрыть режим карты' }).click()
  await expect(page.getByRole('heading', { name: 'Паспорт пожара', exact: true })).toBeVisible()
})

test('closing during loading discards late responses; retry after a work-map error', async ({ page, request }) => {
  await passport(page, request)
  let resolvePending: (() => void) | undefined
  const pending = new Promise<void>(resolve => { resolvePending = resolve })
  let first = true
  await page.route('**/api/v1/events/*/work-map', async route => {
    if (first) { first = false; await pending }
    await route.fulfill({ json: { status: 'error', message: 'Не удалось прочитать данные участка' } }).catch(() => {})
  })
  await page.getByRole('button', { name: 'Участки работ', exact: true }).click()
  await expect(page.getByText('Готовим участки', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Закрыть режим карты' }).click()
  resolvePending!()
  await page.getByRole('button', { name: 'После пожара', exact: true }).click()
  await expect(page.getByRole('slider', { name: 'Разделитель снимков' })).toBeVisible()
  await expect(page.getByText('Не удалось прочитать данные участка', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Закрыть режим карты' }).click()
  await page.getByRole('button', { name: 'Участки работ', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('Не удалось прочитать данные участка')
  await page.unroute('**/api/v1/events/*/work-map')
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByLabel('Легенда участков')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: 'Паспорт пожара', exact: true })).toBeVisible()
})
