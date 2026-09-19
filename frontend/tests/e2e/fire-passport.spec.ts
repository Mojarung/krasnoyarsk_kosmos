import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdir } from 'node:fs/promises'
import type { FireEventDetail, FireEventList, Meta } from '../../src/lib/types'
import type { Map as MapLibre } from 'maplibre-gl'

declare global { interface Window { __fireMap?: { map: MapLibre; draw: unknown } } }

const period = { date_from: '2019-01-01', date_to: '2024-12-31' }
const box = { bbox: [35, 43, 52, 55], ...period }

async function events(request: APIRequestContext, status = 'all', data: object = box): Promise<FireEventList> {
  const response = await request.post(`/api/v1/events?status=${status}&limit=100`, { data })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function start(page: Page) {
  await page.goto('/')
  await expect(page.locator('main > .z-50')).toHaveCount(0, { timeout: 60_000 })
  const summary = page.getByRole('button', { name: 'Паспорта пожаров', exact: true })
  if (!await summary.isVisible()) await page.getByRole('button', { name: /га|Сводка/ }).filter({ hasText: /га|Сводка/ }).first().click()
  await expect(summary).toBeVisible()
}

async function openList(page: Page, status = 'linked') {
  await page.getByRole('button', { name: 'Паспорта пожаров', exact: true }).click()
  await page.getByLabel('Наблюдения', { exact: true }).selectOption(status)
  await expect(page.getByText('Собираем наблюдения', { exact: true })).toBeHidden({ timeout: 60_000 })
}

async function firstDetail(page: Page) {
  await page.getByRole('button', { name: /^Открыть паспорт / }).first().click()
  await expect(page.getByRole('heading', { name: 'История наблюдений' })).toBeVisible()
}

test('API: all five territories, unique identities, linked observations, areas and recovery', async ({ request }) => {
  const meta: Meta = await (await request.get('/api/v1/meta')).json()
  expect(meta.regions.features.length).toBeGreaterThanOrEqual(5)
  const global = await events(request)
  expect(global.total).toBeGreaterThan(0)
  for (const region of meta.regions.features) {
    const list = await events(request, 'all', { geometry: region.geometry, ...period })
    expect(list.total, region.properties.name).toBeGreaterThan(0)
    expect(new Set(list.items.map(e => e.id)).size).toBe(list.items.length)
    const sample = list.items[0]
    const response = await request.get(`/api/v1/events/${sample.id}`)
    expect(response.ok()).toBeTruthy()
    expect((await response.json()).id).toBe(sample.id)
    console.log(`${region.properties.name}: ${list.total} events, sample ${sample.id}`)
  }
  const linked = await events(request, 'linked')
  expect(linked.total).toBeGreaterThan(0)
  for (const item of linked.items) {
    const response = await request.get(`/api/v1/events/${item.id}`)
    expect(response.ok()).toBeTruthy()
    const d: FireEventDetail = await response.json()
    expect(d.evidence.length).toBeGreaterThan(0)
    expect(d.burn!.by_severity.reduce((sum, s) => sum + s.area_ha, 0)).toBeCloseTo(d.burn!.area_ha, 1)
    expect(d.restoration!.items.reduce((sum, r) => sum + r.area_ha, 0)).toBeCloseTo(d.burn!.area_ha, 1)
    expect(d.timeline.reduce((sum, r) => sum + r.hotspot_count, 0)).toBe(d.hotspot_count)
    const resolved = await request.get(`/api/v1/events/resolve?scene_id=${d.scene_ids[0]}`)
    expect((await resolved.json()).id).toBe(d.id)
    for (const proof of d.evidence) expect(proof.distance_m).toBeLessThanOrEqual(375.1)
    const byPoint = await request.get(`/api/v1/events/resolve?hotspot_id=${d.evidence[0].hotspot_id}`)
    expect((await byPoint.json()).id).toBe(d.id)
  }
  console.log(`Validated ${linked.total} linked passports against real API`)
})

test('API: empty, invalid, missing, pagination and separate observations', async ({ request }) => {
  expect((await events(request, 'all', { ...box, date_from: '2099-01-01', date_to: '2099-12-31' })).total).toBe(0)
  expect((await events(request, 'all', { ...box, bbox: [0, 0, 1, 1] })).total).toBe(0)
  for (const url of ['/api/v1/events/no-such-event', '/api/v1/events/resolve?hotspot_id=99999999']) {
    expect((await request.get(url)).status()).toBe(404)
  }
  expect((await request.get('/api/v1/events/resolve')).status()).toBe(422)
  expect((await request.get('/api/v1/events/resolve?hotspot_id=1&scene_id=x')).status()).toBe(422)
  expect((await request.post('/api/v1/events', { data: { ...box, date_from: '2025-01-01' } })).status()).toBe(422)
  expect((await request.post('/api/v1/events?limit=1000', { data: box })).status()).toBe(422)
  const first = await (await request.post('/api/v1/events?limit=2', { data: box })).json()
  const next = await (await request.post('/api/v1/events?limit=2&offset=2', { data: box })).json()
  expect(first.items.some((a: { id: string }) => next.items.some((b: { id: string }) => a.id === b.id))).toBe(false)
  for (const status of ['hotspot_only', 'burn_only']) {
    const list = await events(request, status)
    expect(list.total).toBeGreaterThan(0)
    const d = await (await request.get(`/api/v1/events/${list.items[0].id}`)).json()
    if (status === 'hotspot_only') { expect(d.burn).toBeNull(); expect(d.restoration).toBeNull() }
    else { expect(d.timeline).toHaveLength(0); expect(d.first_seen).toBeNull() }
  }
})

for (const region of ['Ростовская обл.', 'Волгоградская обл.', 'Калмыкия']) {
  test(`UI: territory ${region}, passport, evidence, before/after and return`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await start(page)
    await page.getByRole('button', { name: region, exact: true }).click()
    await openList(page, 'burn_only')
    await firstDetail(page)
    await expect(page.getByText('Только гарь', { exact: true })).toBeVisible()
    await page.getByText('Как связаны данные', { exact: true }).click()
    await expect(page.getByText(/Термоточки объединены цепочкой/)).toBeVisible()
    await page.getByRole('button', { name: /^До и после / }).first().click()
    const comparison = page.getByRole('dialog', { name: 'Сравнение снимков до и после' })
    await expect(comparison).toBeVisible()
    await expect(comparison.locator('img').first()).toBeVisible()
    await expect.poll(() => comparison.locator('img').first().evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBeTruthy()
    await page.getByRole('button', { name: 'Закрыть сравнение' }).click()
    await expect(page.getByRole('heading', { name: 'Паспорт пожара', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('heading', { name: 'Паспорта пожаров', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Закрыть паспорта' }).click()
    await expect(page.getByRole('button', { name: 'Паспорта пожаров', exact: true })).toBeVisible()
    expect(errors).toEqual([])
  })
}

test('UI: filters, error recovery, pagination and rapid selection', async ({ page }) => {
  await start(page)
  await openList(page, 'all')
  const first = await page.getByRole('button', { name: /^Открыть паспорт / }).first().getAttribute('aria-label')
  await page.getByRole('button', { name: 'Следующие события' }).click()
  await expect(page.getByRole('button', { name: /^Открыть паспорт / }).first()).not.toHaveAttribute('aria-label', first!)
  await page.getByRole('button', { name: 'Предыдущие события' }).click()
  await expect(page.getByRole('button', { name: /^Открыть паспорт / }).first()).toHaveAttribute('aria-label', first!)
  await page.route('**/api/v1/events?**', route => route.abort(), { times: 1 })
  await page.getByLabel('Наблюдения', { exact: true }).selectOption('linked')
  await expect(page.getByRole('alert')).toBeVisible()
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await firstDetail(page)
  await expect(page.getByText('Связь предполагается', { exact: true })).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Скачать JSON' }).click()
  expect((await downloadPromise).suggestedFilename()).toMatch(/^bs-.*\.json$/)
  await page.getByRole('button', { name: 'Назад к паспортам' }).click()
  await page.getByLabel('Наблюдения', { exact: true }).selectOption('burn_only')
  await page.getByLabel('Наблюдения', { exact: true }).selectOption('hotspot_only')
  await firstDetail(page)
  await expect(page.getByText('Только термоточки', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'План восстановления' })).toHaveCount(0)
})

test('UI: map hotspot click opens its real passport and restores map layers', async ({ page, request }) => {
  await start(page)
  await openList(page)
  const id = (await page.getByRole('button', { name: /^Открыть паспорт / }).first().getAttribute('aria-label'))!.replace('Открыть паспорт ', '')
  const detail: FireEventDetail = await (await request.get(`/api/v1/events/${id}`)).json()
  await firstDetail(page)
  await page.getByRole('button', { name: 'Закрыть паспорта' }).click()
  await page.getByRole('button', { name: 'Свернуть панель запроса' }).click()
  await page.getByRole('button', { name: 'Скрыть панель' }).click()
  // Read the rendered projection, never drive store state or click handlers.
  test.skip(!await page.evaluate(() => !!window.__fireMap), 'Projection diagnostic is available only in the development build')
  await expect.poll(() => page.evaluate(() => window.__fireMap!.map.isMoving())).toBe(false)
  const ids = detail.map.features.filter(f => f.geometry.type === 'Point').map(f => f.properties!.id)
  const findPoint = () => page.evaluate(wanted => {
    const map = window.__fireMap!.map
    const feature = map.queryRenderedFeatures({ layers: ['fire-core'] }).find(f => wanted.includes(f.properties.id))
    if (!feature || feature.geometry.type !== 'Point') return null
    const p = map.project(feature.geometry.coordinates as [number, number])
    return { x: p.x, y: p.y }
  }, ids)
  await expect.poll(findPoint).not.toBeNull()
  const screen = await findPoint()
  await page.mouse.click(screen!.x, screen!.y)
  await expect(page.getByRole('heading', { name: 'Паспорт пожара', exact: true })).toBeVisible()
  await expect(page.getByText(id, { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Закрыть паспорта' }).click()
  const findBurn = () => page.evaluate(sceneIds => {
    const map = window.__fireMap!.map
    for (let y = 180; y < 600; y += 25) for (let x = 300; x < 900; x += 25) {
      if (map.queryRenderedFeatures([x, y], { layers: ['fire-core'] }).length) continue
      const burn = map.queryRenderedFeatures([x, y], { layers: ['severity-fill', 'burn-fill'] })[0]
      if (burn && sceneIds.includes(burn.properties.scene_id)) return { x, y }
    }
    return null
  }, detail.scene_ids)
  await expect.poll(findBurn).not.toBeNull()
  const burnPoint = await findBurn()
  await page.mouse.click(burnPoint!.x, burnPoint!.y)
  await expect(page.getByText(id, { exact: true })).toBeVisible()
})

test('UI: passport map colors follow a live theme switch', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('fw-theme', 'light'))
  await start(page)
  test.skip(!await page.evaluate(() => !!window.__fireMap), 'Map paint diagnostic is available only in the development build')
  await openList(page)
  await firstDetail(page)
  const colorsMatch = () => page.evaluate(() => {
    const map = window.__fireMap!.map
    const css = getComputedStyle(document.documentElement)
    const severity = map.getPaintProperty('event-burn', 'fill-color') as unknown as unknown[]
    return severity[3] === css.getPropertyValue('--sev-1').trim()
      && map.getPaintProperty('event-hotspot', 'circle-color') === css.getPropertyValue('--fire').trim()
      && map.getPaintProperty('event-outline', 'line-color') === css.getPropertyValue('--primary').trim()
  })
  await expect.poll(colorsMatch).toBe(true)
  await page.getByRole('button', { name: 'Сменить тему' }).click()
  await expect.poll(colorsMatch).toBe(true)
  await expect(page.getByTestId('passport-observation-date')).toBeInViewport()
})

test('UI: custom rectangle and period change scope; empty type is explained', async ({ page }) => {
  await start(page)
  test.skip(!await page.evaluate(() => !!window.__fireMap), 'Drawing readiness diagnostic is available only in the development build')
  await expect.poll(() => page.evaluate(() => window.__fireMap!.map.isMoving())).toBe(false)
  await page.getByRole('button', { name: 'Прямоугольник', exact: true }).click()
  await expect.poll(() => page.evaluate(() => !!window.__fireMap!.draw)).toBe(true)
  await page.mouse.click(550, 270)
  await page.mouse.move(760, 470, { steps: 12 })
  await page.mouse.click(760, 470, { delay: 100 })
  await expect(page.getByText(/Свой полигон/).first()).toBeVisible()
  await page.getByRole('button', { name: /Период/ }).click()
  await page.getByRole('button', { name: '2020', exact: true }).click()
  const response = page.waitForResponse(r => r.url().includes('/api/v1/events?') && r.request().method() === 'POST')
  await openList(page, 'ambiguous')
  const data = (await response).request().postDataJSON()
  expect(data.date_from).toBe('2020-04-01')
  expect(data.date_to).toBe('2020-10-31')
  expect(data.geometry.type).toBe('Polygon')
  await expect(page.getByText(/Событий по этому запросу нет/)).toBeVisible()
})

for (const theme of ['light', 'dark']) {
  for (const size of [{ width: 1440, height: 800 }, { width: 768, height: 1024 }, { width: 375, height: 740 }]) {
    test(`Visual and keyboard: ${theme}, ${size.width}`, async ({ page }) => {
      await page.setViewportSize(size)
      await page.addInitScript(t => localStorage.setItem('fw-theme', t), theme)
      await start(page)
      await openList(page)
      await firstDetail(page)
      await expect(page.getByTestId('passport-observation-date')).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.classList.contains('dark'))).toBe(theme === 'dark')
      const panel = page.getByRole('region', { name: 'Паспорта пожаров', exact: true })
      await expect(panel).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
      expect(await panel.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1)
      const failures = (await new AxeBuilder({ page }).include('section[aria-label="Паспорта пожаров"]').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations
      expect(failures).toEqual([])
      await mkdir('../design/screens/passport', { recursive: true })
      await page.screenshot({ path: `../design/screens/passport/${theme}-${size.width}.png` })
      await page.getByText('Как связаны данные', { exact: true }).click()
      await panel.locator('details p').last().scrollIntoViewIfNeeded()
      await page.screenshot({ path: `../design/screens/passport/${theme}-${size.width}-evidence.png` })
      await page.keyboard.press('Escape')
      await expect(page.getByRole('heading', { name: 'Паспорта пожаров', exact: true })).toBeFocused()
      await page.keyboard.press('Tab')
      await expect(page.getByRole('button', { name: 'Закрыть паспорта' })).toBeFocused()
    })
  }
}
