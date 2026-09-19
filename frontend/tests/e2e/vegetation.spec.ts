import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import type { VegetationReport } from '../../src/lib/vegetation'
import type { FireEventDetail } from '../../src/lib/types'

const events = ['bs-FE08918', 'bs-FE04217', 'bs-FE06923']
const dialog = (page: Page) => page.getByRole('dialog', { name: 'Растительность после пожара' })

async function open(page: Page, event = events[0]) {
  await page.goto('/')
  await expect(page.locator('main > .z-50')).toHaveCount(0, { timeout: 60_000 })
  const summary = page.getByRole('button', { name: 'Паспорта пожаров', exact: true })
  if (!await summary.isVisible()) await page.getByRole('button', { name: /га|Сводка/ }).first().click()
  await summary.click()
  await page.getByLabel('Наблюдения', { exact: true }).selectOption('linked')
  await expect(page.getByText('Собираем наблюдения', { exact: true })).toBeHidden({ timeout: 60_000 })
  await page.getByRole('button', { name: `Открыть паспорт ${event}`, exact: true }).click()
  await page.getByRole('button', { name: 'После пожара', exact: true }).click()
  await expect(dialog(page)).toBeVisible()
}

async function loaded(page: Page) {
  await expect.poll(async () => dialog(page).locator('img').evaluateAll(images => images.length > 0 && images.every(i => (i as HTMLImageElement).complete && (i as HTMLImageElement).naturalWidth > 0)), { timeout: 30_000 }).toBeTruthy()
}

for (const event of events) {
  test(`real API and complete history: ${event}`, async ({ request, page }, info) => {
    test.setTimeout(300_000)
    const started = Date.now()
    const response = await request.post(`/api/v1/events/${event}/vegetation`)
    expect(response.status()).toBe(202)
    let report: VegetationReport = await response.json()
    await expect.poll(async () => {
      report = await (await request.get(`/api/v1/vegetation/${report.id}`)).json()
      return report.status
    }, { timeout: 240_000, intervals: [2000] }).toBe('ready')
    expect(report.frames).toHaveLength(report.years.length)
    expect(report.frames.every(f => f.status === 'ready')).toBeTruthy()
    for (const frame of report.frames) {
      expect(frame.valid_share).toBeGreaterThanOrEqual(.8)
      expect(frame.date).toMatch(new RegExp(`^${frame.year}-(06|07)-`))
      for (const url of [frame.rgb_url, frame.change_url].filter(Boolean)) {
        const image = await request.get(url!)
        expect(image.status()).toBe(200)
        expect(image.headers()['content-type']).toBe('image/webp')
        expect((await image.body()).length).toBeGreaterThan(1000)
      }
      if (frame.comparison?.delta_ndvi != null) {
        expect(frame.comparison.common_share).toBeGreaterThanOrEqual(.8)
        expect(frame.comparison.season_gap_days).toBeLessThanOrEqual(14)
      }
    }
    const cached = await (await request.post(`/api/v1/events/${event}/vegetation`)).json()
    expect(cached.id).toBe(report.id)
    expect(cached.updated_at).toBe((report as VegetationReport & { updated_at: string }).updated_at)
    console.log(`${event}: ${report.frames.length} real frames, cached API ${Date.now() - started}ms including image checks`)
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await open(page, event)
    await loaded(page)
    await expect(dialog(page).getByTestId('vegetation-summary')).toBeVisible()
    await dialog(page).getByRole('switch').click()
    await loaded(page)
    const slider = dialog(page).getByRole('slider')
    await slider.fill('70')
    await expect(slider).toHaveValue('70')
    await page.screenshot({ path: info.outputPath('compare.png') })
    await dialog(page).getByRole('tab', { name: 'Растительность', exact: true }).click()
    await loaded(page)
    await expect(dialog(page).getByText('Меньше зелени', { exact: true })).toBeVisible()
    for (const year of report.years) {
      await dialog(page).getByRole('button', { name: `Снимок за ${year} год` }).click()
      await loaded(page)
    }
    await page.keyboard.press('Escape')
    await expect(dialog(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'История наблюдений' })).toBeVisible()
    await page.getByRole('button', { name: 'После пожара', exact: true }).click()
    await loaded(page)
    await dialog(page).getByRole('button', { name: 'Осмотреть участок' }).click()
    await expect(dialog(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Место осмотра', exact: true })).toBeVisible()
    const detail: FireEventDetail = await (await request.get(`/api/v1/events/${event}`)).json()
    function firstPoint(g: GeoJSON.Geometry): number[] {
      if (g.type === 'GeometryCollection') return firstPoint(g.geometries[0])
      if (g.type === 'MultiPolygon') return g.coordinates[0][0][0]
      if (g.type === 'Polygon') return g.coordinates[0][0]
      throw new Error('Missing burn polygon')
    }
    const site = firstPoint(detail.map.features.find(f => f.properties?.kind === 'burn')!.geometry)
    await page.getByText('Ввести координаты вручную', { exact: true }).click()
    await page.getByLabel('Широта', { exact: true }).fill(String(site[1]))
    await page.getByLabel('Долгота', { exact: true }).fill(String(site[0]))
    await page.getByRole('button', { name: 'Применить координаты' }).click()
    await page.getByRole('button', { name: 'Далее', exact: true }).click()
    await expect(page.getByLabel('Цель осмотра')).toHaveValue('recovery')
    if (event === events[0]) {
      const note = 'E2E vegetation: проверить растительность после сравнения снимков'
      await page.getByLabel('Что проверить').fill(note)
      const saved = page.waitForResponse(r => r.url().endsWith('/api/v1/inspections') && r.request().method() === 'POST')
      await page.getByRole('button', { name: 'Сохранить задание' }).click()
      const response = await saved
      expect(response.status()).toBe(201)
      const task = await response.json()
      expect(task.purpose).toBe('recovery')
      await expect(page.getByText('Задание сохранено', { exact: false })).toBeVisible()
      await page.goto(`/#inspection=${task.share_token}`)
      await expect(page.getByRole('heading', { name: 'Задание на осмотр' })).toBeVisible()
      await expect(page.getByText(note, { exact: true })).toBeVisible()
    }
    expect(errors).toEqual([])
  })
}

for (const theme of ['dark', 'light']) {
  for (const viewport of [{ width: 1440, height: 800 }, { width: 768, height: 1024 }, { width: 375, height: 740 }]) {
    test(`layout ${theme} ${viewport.width}`, async ({ page }, info) => {
      await page.setViewportSize(viewport)
      await page.addInitScript(t => localStorage.setItem('fw-theme', t), theme)
      await open(page)
      await loaded(page)
      await dialog(page).getByRole('tab', { name: 'Растительность', exact: true }).click()
      await loaded(page)
      await expect(dialog(page).getByTestId('vegetation-summary')).toBeInViewport()
      await expect(dialog(page).getByText('Меньше зелени', { exact: true })).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
      const results = await new AxeBuilder({ page }).include('[aria-label="Растительность после пожара"]').analyze()
      expect(results.violations).toEqual([])
      await page.screenshot({ path: info.outputPath(`${theme}-${viewport.width}.png`) })
    })
  }
}

test('fault injection: partial result, retry and failed baseline image', async ({ page, request }) => {
  const ready: VegetationReport = await (await request.post(`/api/v1/events/${events[0]}/vegetation`)).json()
  const broken = structuredClone(ready)
  broken.status = 'partial'
  const latest = broken.years.at(-1)!
  broken.frames = broken.frames.map(f => f.year === latest ? { year: latest, status: 'error', message: 'Источник снимков временно недоступен' } : f)
  await page.route('**/events/*/vegetation*', route => route.fulfill({ json: route.request().url().includes('retry=true') ? ready : broken }))
  await open(page)
  await expect(dialog(page).getByText('Источник снимков временно недоступен', { exact: true })).toBeVisible()
  await dialog(page).getByRole('button', { name: 'Догрузить пропуски' }).click()
  await loaded(page)
  let first = true
  await page.route(`**/${ready.baseline_year}/rgb.webp*`, route => {
    if (first) { first = false; return route.fulfill({ status: 503, body: 'unavailable' }) }
    return route.continue()
  })
  await dialog(page).getByRole('switch').click()
  await expect(dialog(page).getByText('Снимок не загрузился', { exact: true })).toBeVisible()
  await dialog(page).getByRole('button', { name: 'Повторить снимок' }).click()
  await loaded(page)
  await expect(dialog(page).getByText('Снимок не загрузился', { exact: true })).toHaveCount(0)
})

test('API rejects unknown events, thermopoints, unsafe identifiers and unready images', async ({ request }) => {
  expect((await request.post('/api/v1/events/af-1/vegetation')).status()).toBe(422)
  expect((await request.post('/api/v1/events/bs-no-such-event/vegetation')).status()).toBe(404)
  expect((await request.get('/api/v1/vegetation/not-a-job')).status()).toBe(422)
  expect((await request.get('/api/v1/vegetation/00000000000000000000000000000000')).status()).toBe(404)
  expect((await request.get('/api/v1/vegetation/00000000000000000000000000000000/2020/rgb.webp')).status()).toBe(404)
})

test('fault injection: background loading and polling recover after temporary network failure', async ({ page, request }) => {
  const ready: VegetationReport = await (await request.post(`/api/v1/events/${events[0]}/vegetation`)).json()
  const pending = { ...ready, status: 'running', active_year: ready.years.at(-1), frames: [] }
  let polls = 0
  await page.route('**/events/*/vegetation*', route => route.fulfill({ json: pending }))
  await page.route(`**/vegetation/${ready.id}`, route => {
    polls++
    return polls === 1 ? route.fulfill({ status: 503, json: { detail: 'Временный сбой связи' } }) : route.fulfill({ json: ready })
  })
  await open(page)
  await expect(dialog(page).getByText('Можно закрыть — загрузка продолжится', { exact: true })).toBeVisible()
  await expect(dialog(page).getByRole('alert')).toContainText('Временный сбой связи')
  await loaded(page)
  await expect(dialog(page).getByRole('alert')).toHaveCount(0)
  expect(polls).toBeGreaterThanOrEqual(2)
})

test('fault injection: cloudy and missing observations never become zero vegetation', async ({ page, request }) => {
  const report: VegetationReport = await (await request.post(`/api/v1/events/${events[0]}/vegetation`)).json()
  const latest = report.frames.at(-1)!
  report.status = 'partial'
  latest.status = 'cloudy'; latest.valid_share = .4
  latest.comparison = { ...latest.comparison!, common_share: .4, delta_ndvi: null, current_ndvi: null, baseline_ndvi: null }
  report.frames[1] = { year: report.years[1], status: 'missing', message: 'Нет снимка с полным покрытием участка' }
  await page.route('**/events/*/vegetation*', route => route.fulfill({ json: report }))
  await open(page)
  await loaded(page)
  await expect(dialog(page).getByTestId('vegetation-summary')).toContainText('Меньше 80%')
  await expect(dialog(page).getByRole('button', { name: `Снимок за ${latest.year} год` })).toContainText('частично')
  await dialog(page).getByRole('button', { name: `Снимок за ${report.years[1]} год` }).click()
  await expect(dialog(page).getByText('Нет снимка с полным покрытием участка', { exact: true })).toBeVisible()
  await expect(dialog(page).getByTestId('vegetation-summary')).toHaveCount(0)
})
