import { test, expect, chromium, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { mkdir } from 'node:fs/promises'
import AxeBuilder from '@axe-core/playwright'
import type { FireEventDetail } from '../../src/lib/types'
import type { Inspection } from '../../src/lib/inspections'
import { inspectionMapUrl, inspectionText, routeUrl } from '../../src/lib/inspections'
import { territoryBounds, yandexMapsUrl } from '../../src/lib/yandex-maps'

const NOTE = 'E2E inspection: проверить растительность у дороги'
function point(detail: FireEventDetail): [number, number] {
  const feature = detail.map.features.find(f => f.properties?.kind === 'burn')!
  function first(g: GeoJSON.Geometry): [number, number] {
    if (g.type === 'GeometryCollection') return first(g.geometries[0])
    if (g.type === 'Polygon') return g.coordinates[0][0] as [number, number]
    if (g.type === 'MultiPolygon') return g.coordinates[0][0][0] as [number, number]
    throw new Error('Expected burn geometry')
  }
  return first(feature.geometry)
}

test('links: coordinate order, whole geometry and direct Yandex URL', () => {
  expect(routeUrl([46.557949, 48.698816])).toBe('https://yandex.ru/maps/?rtext=%7E48.698816%2C46.557949&rtt=auto')
  const route = new URL(routeUrl([41.5, 47.2]))
  expect(route.searchParams.get('rtext')).toBe('~47.2,41.5')
  expect(yandexMapsUrl([NaN, 1, 3, 4])).toBeNull()
  expect(territoryBounds(null)).toBeNull()
  const bounds = territoryBounds({ type: 'MultiPolygon', coordinates: [[[[41, 46], [42, 46], [42, 47], [41, 46]]], [[[43, 48], [44, 48], [44, 49], [43, 48]]]] })
  expect(bounds).toEqual([41, 46, 44, 49])
  expect(new URL(yandexMapsUrl(bounds)!).searchParams.get('ll')?.split(',')[0]).toBe('42.500000')
})

test('API: real save, idempotency, validation, event list and read-only share', async ({ request }) => {
  const detail: FireEventDetail = await (await request.get('/api/v1/events/bs-FE17518')).json()
  const site = point(detail)
  const payload = { id: randomUUID(), event_id: detail.id, purpose: 'damage', note: NOTE, site, access: [site[0] + 0.001, site[1]] }
  const results = await Promise.all([request.post('/api/v1/inspections', { data: payload }), request.post('/api/v1/inspections', { data: payload })])
  for (const r of results) expect(r.status(), await r.text()).toBe(201)
  const task: Inspection = await results[0].json()
  expect((await results[1].json()).share_token).toBe(task.share_token)
  const shared = await request.get(`/api/v1/inspections/shared/${task.share_token}`)
  expect(shared.status()).toBe(200)
  expect(shared.headers()['cache-control']).toBe('no-store')
  expect((await shared.json()).note).toBe(NOTE)
  expect((await (await request.get(`/api/v1/inspections?event_id=${detail.id}`)).json()).items.filter((t: Inspection) => t.id === task.id)).toHaveLength(1)
  expect((await request.post('/api/v1/inspections', { data: { ...payload, note: 'changed' } })).status()).toBe(409)
  for (const changes of [{ site: [0, 0] }, { site: [181, 48] }, { access: [0, 0] }, { purpose: 'bad' }, { note: 'x'.repeat(1001) }]) {
    expect((await request.post('/api/v1/inspections', { data: { ...payload, id: randomUUID(), ...changes } })).status()).toBe(422)
  }
  expect((await request.post('/api/v1/inspections', { data: { ...payload, id: randomUUID(), event_id: 'missing' } })).status()).toBe(404)
  expect((await request.get('/api/v1/inspections/shared/missing')).status()).toBe(404)
  expect((await request.patch(`/api/v1/inspections/shared/${task.share_token}`, { data: { note: 'changed' } })).status()).toBe(405)
})

async function openPassport(page: Page): Promise<FireEventDetail> {
  await page.goto('/')
  await expect(page.locator('main > .z-50')).toHaveCount(0, { timeout: 60_000 })
  const open = page.getByRole('button', { name: 'Паспорта пожаров', exact: true })
  if (!await open.isVisible()) await page.getByRole('button', { name: /га|Сводка/ }).filter({ hasText: /га|Сводка/ }).first().click()
  await open.click()
  await page.getByLabel('Наблюдения', { exact: true }).selectOption('burn_only')
  const response = page.waitForResponse(r => /\/api\/v1\/events\/bs-/.test(r.url()) && r.request().method() === 'GET')
  await page.getByRole('button', { name: /^Открыть паспорт / }).first().click()
  const detail = await (await response).json()
  await expect(page.getByRole('button', { name: 'Запланировать осмотр', exact: true })).toBeVisible()
  return detail
}

for (const width of [1440, 375]) {
  test(`UI ${width}: create inspection, pick access, recover network failure, share and reopen`, async ({ page, context }) => {
    await page.setViewportSize({ width, height: 900 })
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    const detail = await openPassport(page)
    const site = point(detail)
    await page.getByRole('button', { name: 'Запланировать осмотр', exact: true }).click()
    const panel = page.getByRole('region', { name: 'Планирование осмотра' })
    await expect(page.getByRole('button', { name: 'Далее' })).toBeDisabled()
    await page.getByText('Ввести координаты вручную', { exact: true }).click()
    await page.getByLabel('Широта', { exact: true }).fill(String(site[1]))
    await page.getByLabel('Долгота', { exact: true }).fill(String(site[0]))
    await page.getByRole('button', { name: 'Применить координаты' }).click()
    await page.getByRole('button', { name: 'Закрыть планирование' }).click()
    await expect(page.getByText('Выйти без сохранения задания?')).toBeVisible()
    await page.getByRole('button', { name: 'Продолжить', exact: true }).click()
    await page.getByRole('button', { name: 'Далее' }).click()
    await page.getByLabel('Цель осмотра').selectOption('recovery')
    await page.getByLabel('Что проверить').fill(NOTE)
    await page.getByRole('button', { name: 'Выбрать место остановки' }).click()
    await expect(page.getByText('2 · Выберите место остановки', { exact: true })).toBeVisible()
    // Actual map click; the panel is hidden and the whole canvas is available.
    await page.locator('.maplibregl-canvas').click({ position: { x: Math.round(width / 2), y: 200 } })
    await expect(page.getByLabel('Цель осмотра')).toHaveValue('recovery')
    await expect(page.getByLabel('Что проверить')).toHaveValue(NOTE)
    // Ensure deterministic nearby access for geographic validation and route assertions.
    await page.getByLabel('Для какой точки').selectOption('access')
    await page.getByLabel('Широта', { exact: true }).fill(String(site[1]))
    await page.getByLabel('Долгота', { exact: true }).fill(String(site[0] + 0.001))
    await page.getByRole('button', { name: 'Применить координаты' }).click()
    await mkdir('../design/screens/inspections', { recursive: true })
    await panel.screenshot({ path: `../design/screens/inspections/planner-${width}.png` })
    await page.route('**/api/v1/inspections', route => route.abort(), { times: 1 })
    await page.getByRole('button', { name: 'Сохранить задание' }).click()
    await expect(panel.getByRole('alert')).toBeVisible()
    await expect(page.getByLabel('Что проверить')).toHaveValue(NOTE)
    const saveResponse = page.waitForResponse(r => r.url().endsWith('/api/v1/inspections') && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'Сохранить задание' }).click()
    const task: Inspection = await (await saveResponse).json()
    expect(task.id).toBeTruthy()
    await expect(page.getByText('Задание сохранено', { exact: false })).toBeVisible()
    expect(new URL((await page.getByRole('link', { name: 'Маршрут в Яндекс Картах' }).getAttribute('href'))!).searchParams.get('rtext')).toBe(`~${task.access![1]},${task.access![0]}`)
    await page.getByRole('button', { name: 'Скопировать задание' }).click()
    await expect(page.getByText('Задание скопировано', { exact: true })).toBeAttached()
    await expect(page.getByRole('button', { name: 'QR', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Ссылка на Яндекс Карты', exact: true }).click()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(routeUrl(task.access!))
    await page.getByRole('button', { name: 'Ссылка на карточку', exact: true }).click()
    const cardLink = await page.evaluate(() => navigator.clipboard.readText())
    expect(new URL(cardLink).hash).toBe(`#inspection=${task.share_token}`)
    const violations = (await new AxeBuilder({ page }).include('[aria-label="Планирование осмотра"]').withTags(['wcag2a', 'wcag2aa']).analyze()).violations
    expect(violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.html) }))).toEqual([])
    await panel.screenshot({ path: `../design/screens/inspections/card-${width}.png` })
    await page.getByRole('button', { name: 'Закрыть планирование' }).click()
    await expect(page.getByRole('region', { name: 'Осмотры участка' }).getByRole('button', { name: /Оценить восстановление/ }).first()).toBeVisible()
    await page.goto(cardLink)
    await expect(page.getByRole('heading', { name: 'Задание на осмотр' })).toBeVisible()
    await expect(page.getByText(NOTE, { exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByText(NOTE, { exact: true })).toBeVisible()
    await expect(page.getByLabel('Карта места осмотра и остановки').locator('canvas')).toBeVisible()
    await expect(page.locator('.inspection-marker')).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Сохранить задание' })).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    await page.screenshot({ path: `../design/screens/inspections/shared-${width}.png`, fullPage: true })
    expect(errors).toEqual([])
  })
}

test('shared card: missing token is recoverable', async ({ page }) => {
  await page.goto('/#inspection=does-not-exist')
  await expect(page.getByRole('alert')).toContainText('Карточка не найдена')
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Карточка не найдена')
})

test('direct Yandex link without access; HTTP clipboard fallback', async ({ request }) => {
  const detail: FireEventDetail = await (await request.get('/api/v1/events/bs-FE17518')).json()
  const response = await request.post('/api/v1/inspections', { data: { id: randomUUID(), event_id: detail.id, purpose: 'boundary', note: NOTE, site: point(detail), access: null } })
  expect(response.status()).toBe(201)
  const task: Inspection = await response.json()
  // Local test DNS alias exercises non-localhost HTTP without exposing the server publicly.
  const browser = await chromium.launch({ args: ['--host-resolver-rules=MAP firewatch.test 127.0.0.1', '--no-proxy-server'] })
  try {
    const page = await browser.newPage({ viewport: { width: 375, height: 812 } })
    // Use the production web server: Vite deliberately rejects unknown Host names.
    const url = new URL(`/#inspection=${task.share_token}`, process.env.SHARE_APP_URL ?? 'http://localhost:8080')
    url.hostname = 'firewatch.test'
    await page.goto(url.toString())
    await expect(page.getByText(NOTE, { exact: true })).toBeVisible()
    await expect(page.getByLabel('Карта места осмотра и остановки').locator('canvas')).toBeVisible()
    await expect(page.locator('.inspection-marker')).toHaveCount(1)
    await expect(page.getByRole('link', { name: 'Маршрут в Яндекс Картах' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Ссылка на Яндекс Карты', exact: true }).click()
    await expect(page.getByLabel('Текст для ручного копирования')).toHaveValue(inspectionMapUrl(task))
    await page.getByRole('button', { name: 'Ссылка на карточку', exact: true }).click()
    await expect(page.getByLabel('Текст для ручного копирования')).toHaveValue(url.toString())
    await expect(page.getByRole('button', { name: 'QR', exact: true })).toHaveCount(0)
    expect(new URL(inspectionMapUrl(task)).hostname).toBe('yandex.ru')
    expect(inspectionText(task)).not.toContain('localhost')

  } finally { await browser.close() }
})

test('map: pick actual burn point, cancel replacement, save without access', async ({ page }) => {
  const detail = await openPassport(page)
  test.skip(!await page.evaluate(() => !!window.__fireMap), 'Read-only projection diagnostic requires DEV build')
  await page.getByRole('button', { name: 'Запланировать осмотр', exact: true }).click()
  await page.getByRole('button', { name: 'Выбрать место на карте', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.__fireMap!.map.isMoving())).toBe(false)
  const site = point(detail)
  const p = await page.evaluate(coords => { const p = window.__fireMap!.map.project(coords); return { x: p.x, y: p.y } }, site)
  await page.locator('.maplibregl-canvas').click({ position: p })
  await expect(page.getByText('1 · Место выбрано')).toBeVisible()
  await expect(page.locator('.inspection-marker')).toHaveCount(1)
  await page.getByRole('button', { name: 'Переставить место осмотра' }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('region', { name: 'Планирование осмотра' })).toBeVisible()
  await page.getByRole('button', { name: 'Далее' }).click()
  await page.getByLabel('Что проверить').fill(NOTE)
  await page.getByRole('button', { name: 'Сохранить задание' }).click()
  await expect(page.getByText('Задание сохранено')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Маршрут в Яндекс Картах' })).toHaveCount(0)
})
