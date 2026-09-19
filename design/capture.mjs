/**
 * Съёмка состояния интерфейса. Запускать при поднятом сервисе:
 *   node design/capture.mjs before      → design/screens/before/
 *   node design/capture.mjs after       → design/screens/after/
 *   node design/capture.mjs iteration-3 → design/screens/iteration-3/
 *
 * Требует playwright. Если его нет в проекте:  npx playwright@latest install chromium
 * и запускать через  npx -p playwright node design/capture.mjs <метка>
 */
import { chromium } from 'playwright'
import path from 'node:path'
import fs from 'node:fs'

const label = process.argv[2] || 'before'
const base = process.env.APP_URL || 'http://localhost:8080'
const out = path.resolve('design/screens', label)
fs.mkdirSync(out, { recursive: true })

// Ширины из правил проекта плюс низкая высота: закреплённые панели съедают
// ноутбучный экран, а на высоком мониторе всё сходится (наблюдение 0102).
const sizes = [
  { tag: 'desktop', width: 1440, height: 900 },
  { tag: 'laptop', width: 1440, height: 760 },
  { tag: 'tablet', width: 768, height: 1024 },
  { tag: 'mobile', width: 375, height: 740 },
]

// Экраны обзора. Панели открываются кликом, поэтому шаги описаны действиями.
const shots = [
  { name: '01-overview', steps: [] },
  { name: '02-dynamics', steps: [{ click: 'text=Очаги пожаров' }] },
  { name: '03-alarms', steps: [{ click: 'text=Ложные тревоги' }] },
  { name: '04-restoration', steps: [{ click: 'text=Что делать с гарями' }] },
  { name: '05-pipeline', steps: [{ click: '[aria-label*="Конвейер"], button:has-text("Конвейер")' }] },
]

const browser = await chromium.launch()
const problems = []

for (const theme of ['light', 'dark']) {
  for (const s of sizes) {
    const ctx = await browser.newContext({
      viewport: { width: s.width, height: s.height },
      colorScheme: theme,
      locale: 'ru-RU',
    })
    /**
     * Приложение хранит тему в localStorage и не смотрит на prefers-color-scheme,
     * поэтому colorScheme выше не переключает ничего: без этой строки обе «темы»
     * снимались тёмными, а отчёт бодро сообщал про две. Basemap хранится отдельно.
     */
    await ctx.addInitScript(([t, b]) => {
      try {
        localStorage.setItem('fw-theme', t)
        localStorage.setItem('fw-basemap', b)
      } catch { /* приватное окно — тема останется по умолчанию, контроль ниже это поймает */ }
    }, [theme, theme])

    const page = await ctx.newPage()
    const errs = []
    page.on('pageerror', (e) => errs.push(String(e)))
    page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text().slice(0, 200)) })

    try {
      await page.goto(base, { waitUntil: 'networkidle', timeout: 60_000 })
    } catch {
      problems.push(`${base} не открылся на ${s.tag}/${theme} — сервис запущен?`)
      await ctx.close()
      continue
    }
    // ждём, пока уйдёт сплэш с загрузчиком
    await page.waitForTimeout(3500)

    // Положительный контроль: снимок обязан быть в той теме, которую запросили.
    const isDark = await page.evaluate(() => document.documentElement.classList.contains('dark'))
    if (isDark !== (theme === 'dark')) {
      problems.push(`ТЕМА НЕ ПЕРЕКЛЮЧИЛАСЬ: просили ${theme}, на странице ${isDark ? 'dark' : 'light'} — снимки этой темы недействительны`)
      await ctx.close()
      continue
    }

    for (const shot of shots) {
      for (const step of shot.steps) {
        const el = page.locator(step.click).first()
        if (await el.count()) { await el.click({ timeout: 5000 }).catch(() => {}) ; await page.waitForTimeout(900) }
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      if (overflow > 1) problems.push(`${shot.name} ${s.tag}/${theme}: горизонтальный скролл ${overflow}px`)
      await page.screenshot({ path: path.join(out, `${shot.name}-${s.tag}-${theme}.png`) })
      await page.keyboard.press('Escape').catch(() => {})
      await page.waitForTimeout(400)
    }

    if (errs.length) problems.push(`${s.tag}/${theme}: ошибки страницы — ${[...new Set(errs)].slice(0, 3).join(' | ')}`)
    await ctx.close()
  }
}

await browser.close()
console.log(`снято в ${out}`)
console.log(problems.length ? problems.join('\n') : 'обе темы сняты, горизонтального скролла и ошибок страниц нет')
