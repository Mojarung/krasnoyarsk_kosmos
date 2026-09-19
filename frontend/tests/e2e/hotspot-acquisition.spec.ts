import { test, expect, type Page } from '@playwright/test'

async function openHotspot(page: Page) {
  await page.goto('/')
  await expect(page.locator('main > .z-50')).toHaveCount(0, { timeout: 60_000 })
  const passports = page.getByRole('button', { name: 'Паспорта пожаров', exact: true })
  if (!await passports.isVisible()) await page.getByRole('button', { name: /га|Сводка/ }).first().click()
  await passports.click()
  await page.getByLabel('Наблюдения', { exact: true }).selectOption('hotspot_only')
  await expect(page.getByText('Собираем наблюдения', { exact: true })).toBeHidden()
  await page.getByRole('button', { name: /^Открыть паспорт / }).first().click()
}

test('search starts once, persists reopening, and opens the real linked passport', async ({ page, request }) => {
  const linked = await (await request.post('/api/v1/events?status=linked&limit=1', {
    data: { bbox: [35, 43, 52, 55], date_from: '2019-01-01', date_to: '2024-12-31' },
  })).json()
  const target = linked.items[0].id
  let status = 'idle', starts = 0
  await page.route('**/api/v1/events/*/acquisition*', async route => {
    if (route.request().method() === 'POST') { starts++; status = 'running' }
    await route.fulfill({ json: { status, event_id: target, jobs: status === 'idle' ? [] : [
      { id: 'test-job', scene_id: 'test-scene', status: 'running', stage: 'acquire', progress: 0.1, error: null },
    ] } })
  })
  await openHotspot(page)
  await page.getByRole('button', { name: 'Найти гарь по снимкам', exact: true }).click()
  await expect(page.getByText('Подбираем и загружаем снимки', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Найти гарь по снимкам', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Назад к паспортам' }).click()
  await page.getByRole('button', { name: /^Открыть паспорт / }).first().click()
  await expect(page.getByText('Подбираем и загружаем снимки', { exact: true })).toBeVisible()
  expect(starts).toBe(1)
  status = 'found'
  await page.getByRole('button', { name: 'Открыть найденную гарь', exact: true }).click()
  await expect(page.getByText(target, { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'После пожара', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^До и после / }).first()).toBeVisible()
  await page.screenshot({ path: '/tmp/hotspot-acquisition-found.png' })
})

for (const status of ['failed', 'not_found', 'ambiguous'] as const) {
  test(`terminal state ${status} is honest and compact`, async ({ page }) => {
    let retry = false
    await page.route('**/api/v1/events/*/acquisition*', async route => {
      if (route.request().method() === 'POST') retry = route.request().url().includes('retry=true')
      await route.fulfill({ json: { status: retry ? 'running' : status, event_id: 'test-event', jobs: [
        { id: 'test-job', scene_id: 'test-scene', status: retry ? 'running' : status === 'failed' ? 'failed' : 'done', stage: 'acquire', progress: 0,
          error: status === 'failed' ? 'Недостаточно ясных снимков у термоточек' : null },
      ] } })
    })
    await openHotspot(page)
    if (status === 'failed') {
      await expect(page.getByText('Недостаточно ясных снимков у термоточек', { exact: true })).toBeVisible()
      await page.getByRole('button', { name: 'Повторить поиск', exact: true }).click()
      await expect(page.getByText('Подбираем и загружаем снимки', { exact: true })).toBeVisible()
      expect(retry).toBe(true)
    } else if (status === 'not_found') {
      await expect(page.getByText('Снимки проверены. Гарь рядом с термоточками не выявлена.', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Открыть найденную гарь', exact: true })).toHaveCount(0)
    } else {
      await expect(page.getByRole('button', { name: 'Проверить варианты связи', exact: true })).toBeVisible()
    }
  })
}
