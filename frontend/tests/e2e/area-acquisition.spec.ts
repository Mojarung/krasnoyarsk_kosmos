import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('custom territory loads hotspots and queues burns without opening pipeline', async ({ page }) => {
  test.setTimeout(120_000)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  let requestBody: { date_pre?: string; date_post?: string; geometry?: { type?: string } } = {}
  await page.route('**/api/v1/acquisitions', async route => {
    requestBody = route.request().postDataJSON() as typeof requestBody
    await route.fulfill({
      status: 202,
      json: {
        jobs: [{ job_id: 'area-job', scene_id: 'BS_live_area' }],
        hotspots: { status: 'ready', imported: 3, existing: 0, products: ['VIIRS_NOAA20_SP'] },
        burns: { status: 'queued', jobs: 1 },
      },
    })
  })

  await page.goto('/')
  await expect(page.locator('main > .z-50')).toHaveCount(0, { timeout: 60_000 })
  await page.getByRole('button', { name: 'Прямоугольник', exact: true }).click()
  const canvas = page.locator('.maplibregl-canvas').first()
  await canvas.click({ position: { x: 500, y: 260 } })
  await canvas.click({ position: { x: 610, y: 360 } })

  const territory = page.getByRole('region', { name: 'Данные выбранной территории' })
  await expect(territory).toBeVisible()
  await expect(page.getByRole('dialog', { name: 'Конвейер обработки' })).toHaveCount(0)
  await territory.getByRole('button', { name: 'Изменить период' }).click()
  await page.getByLabel('с', { exact: true }).fill('2024-08-01')
  await page.getByLabel('по', { exact: true }).fill('2024-08-20')
  await expect(territory.getByText('19 дн.')).toBeVisible()

  await territory.getByRole('button', { name: /^(Получить|Обновить) данные$/ }).click()
  await expect(territory.getByText('Термоточки: добавлено 3.')).toBeVisible()
  await expect(territory.getByText(/Гари: в обработке 1 чип/)).toBeVisible()
  expect(requestBody.date_pre).toBe('2024-08-01')
  expect(requestBody.date_post).toBe('2024-08-20')
  expect(requestBody.geometry?.type).toBe('Polygon')

  const violations = (await new AxeBuilder({ page }).include('[aria-label="Данные выбранной территории"]').withTags(['wcag2a', 'wcag2aa']).analyze()).violations
  expect(violations.map(item => item.id)).toEqual([])
  await page.screenshot({ path: '/tmp/area-acquisition-desktop.png' })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(territory).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: '/tmp/area-acquisition-mobile.png' })
  expect(errors).toEqual([])
})

test('large territory keeps hotspot success and explains skipped burn detail', async ({ page }) => {
  await page.route('**/api/v1/acquisitions', route => route.fulfill({
    status: 202,
    json: {
      jobs: [],
      hotspots: { status: 'ready', imported: 27, existing: 0, products: ['VIIRS_NOAA20_SP'] },
      burns: { status: 'skipped', jobs: 0, message: 'Область 47 x 36 км не помещается в 4 чипа по 10.24 x 10.24 км' },
    },
  }))
  await page.goto('/')
  await expect(page.locator('main > .z-50')).toHaveCount(0, { timeout: 60_000 })
  await page.getByRole('button', { name: 'Прямоугольник', exact: true }).click()
  const canvas = page.locator('.maplibregl-canvas').first()
  await canvas.click({ position: { x: 470, y: 230 } })
  await canvas.click({ position: { x: 700, y: 430 } })
  const territory = page.getByRole('region', { name: 'Данные выбранной территории' })
  await territory.getByRole('button', { name: 'Изменить период' }).click()
  await page.getByLabel('с', { exact: true }).fill('2024-08-01')
  await page.getByLabel('по', { exact: true }).fill('2024-08-20')
  await territory.getByRole('button', { name: /^(Получить|Обновить) данные$/ }).click()
  await expect(territory.getByText('Термоточки: добавлено 27.')).toBeVisible()
  await expect(territory.getByText(/Гари не запущены: Область 47 x 36 км/)).toBeVisible()
})
