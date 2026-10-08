import { test, expect } from '@playwright/test';

test('历史试卷卡片完整包裹内容，桌面与手机打开和分享入口独立', async ({ page }, info) => {
  await page.request.post('/api/login', { data: { code: 'browser-test-only' } });
  const titles = [
    '概率论与数理统计 · 章节练习',
    '离散数学 · 命题逻辑',
    '计算机组成原理 · 第一章',
    '长标题 · ' + 'LongTitle'.repeat(9),
    '概率论 · 期末复习',
    '离散数学 · 图论',
    '计算机组成原理 · 指令系统',
  ];
  const ids: string[] = [];
  for (const [index, title] of titles.entries()) {
    const response = await page.request.post('/api/imports/study-pack', {
      data: {
        format: 'zhixi-study-pack',
        version: 1,
        kind: 'exam',
        title,
        course: index === 3 ? '长课程名称' + 'ABC'.repeat(20) : 'UI 核验课程',
        questions: [
          {
            type: 'choice',
            points: 5,
            stem: '事件的概率最大值为多少？',
            options: ['1', '2', '3', '4'],
            answer: 'A',
          },
        ],
      },
    });
    expect(response.status()).toBe(201);
    ids.push((await response.json()).id);
  }
  // Include a pending card to cover the layout without a share action.
  await page.route('**/api/exams?*', async (route) => {
    const response = await route.fetch();
    const exams = await response.json();
    await route.fulfill({
      json: [
        ...exams,
        {
          ...exams[0],
          id: 'pending-example',
          title: '等待生成的试卷',
          status: 'paused',
          ready_count: 0,
        },
      ],
    });
  });
  await page.goto('/exams');
  await expect(page.locator('.exam-card')).toHaveCount(8);
  async function verifyCards() {
    const results = await page.locator('.exam-card').evaluateAll((cards) =>
      cards.map((card) => {
        const box = card.getBoundingClientRect();
        const main = card.querySelector('.exam-card-main')!;
        const inside = [
          ...card.querySelectorAll(
            'h3, .exam-card-top, .exam-card-details, .exam-card-footer, .exam-card-actions',
          ),
        ].every((child) => {
          const rect = child.getBoundingClientRect();
          return (
            rect.left >= box.left &&
            rect.right <= box.right + 1 &&
            rect.top >= box.top &&
            rect.bottom <= box.bottom + 1
          );
        });
        return {
          fragments: card.getClientRects().length,
          background: getComputedStyle(card).backgroundColor,
          mainFragments: main.getClientRects().length,
          inside,
          nestedLinks: card.querySelectorAll('a a').length,
        };
      }),
    );
    expect(
      results.every(
        (r) =>
          r.fragments === 1 &&
          r.mainFragments === 1 &&
          r.inside &&
          r.nestedLinks === 0 &&
          r.background === 'rgb(255, 255, 255)',
      ),
    ).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await verifyCards();
  const cards = page.locator('.exam-card');
  const first = await cards.nth(0).boundingBox(),
    third = await cards.nth(2).boundingBox(),
    fourth = await cards.nth(3).boundingBox();
  expect(first!.y).toBe(third!.y);
  expect(fourth!.y).toBeGreaterThanOrEqual(first!.y + first!.height);
  await expect(
    cards.filter({ hasText: '等待生成的试卷' }).getByRole('link', { name: '分享到学习库' }),
  ).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('archive-desktop.png'), fullPage: true });
  await page.locator(`.exam-card-main[href="/exams/${ids[0]}"]`).click();
  await expect(page).toHaveURL(`/exams/${ids[0]}`);
  await expect(page.getByRole('heading', { name: titles[0], exact: true })).toBeVisible();
  await page.goto('/exams');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(cards).toHaveCount(8);
  await verifyCards();
  const mobileFirst = await cards.nth(0).boundingBox(),
    mobileSecond = await cards.nth(1).boundingBox();
  expect(mobileSecond!.y).toBeGreaterThanOrEqual(mobileFirst!.y + mobileFirst!.height);
  await page.screenshot({ path: info.outputPath('archive-mobile.png'), fullPage: true });
  await page.getByRole('link', { name: '分享到学习库', exact: true }).first().click();
  await expect(page).toHaveURL(/\/library\?share=[a-f0-9]+$/);
  await expect(page.getByText('本机学习库已就绪', { exact: false })).toBeVisible();
});
