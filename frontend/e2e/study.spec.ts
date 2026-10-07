import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

test('教材 → 组卷 → 作答评分 → 错题 → 分离打印，覆盖桌面与手机', async ({
  page,
  context,
}, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));
  await page.goto('/');
  await page.getByLabel('访问口令').fill('browser-test-only');
  await page.getByRole('button', { name: '开始学习', exact: true }).click();
  await expect(page.getByRole('heading', { name: '今天，也学得更扎实一点。' })).toBeVisible();
  await page.getByRole('link', { name: '我的课程', exact: true }).click();
  await page.getByRole('button', { name: '添加课程', exact: true }).click();
  await page.getByLabel('课程名称').fill('概率论与数理统计');
  await page.getByLabel('课程说明').fill('随机事件、条件概率与独立性 · 本科课程');
  await page.getByRole('dialog').getByRole('button', { name: '创建课程', exact: true }).click();
  await expect(page.getByRole('heading', { name: '概率论与数理统计', exact: true })).toBeVisible();
  const pdf = execFileSync(
    '.venv/bin/python',
    [
      '-c',
      'from tests.test_api import sample_pdf; import sys; sys.stdout.buffer.write(sample_pdf())',
    ],
    { cwd: '..' },
  );
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: '概率论教材.pdf', mimeType: 'application/pdf', buffer: pdf });
  await expect(page.getByRole('heading', { name: '概率论教材.pdf' })).toBeVisible();
  await page.getByRole('button', { name: '预览与修正' }).click();
  await expect(page.locator('.page-text')).toContainText('Probability');
  await page.getByRole('button', { name: '修正此页内容' }).click();
  await page
    .getByLabel('页面解析文本')
    .fill(
      '事件独立性：若事件 A 与 B 独立，则 $P(A\\cap B)=P(A)P(B)$。独立与互斥不同，独立事件可以同时发生。设 $P(A)=0.4$，$P(B)=0.5$，则交集概率为 $0.2$。',
    );
  await page.getByRole('button', { name: '保存修正' }).click();
  await expect(page.getByText('页面修正已保存。')).toBeVisible();
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('link', { name: '生成测验', exact: true }).click();
  await page.getByLabel('试卷名称').fill('独立事件 · 第一章巩固练习');
  await page.locator('.scope-title input').check();
  await page.getByLabel('选择题数量').fill('1');
  await page.getByLabel('计算题数量').fill('1');
  await page.getByRole('button', { name: '预览检索片段' }).click();
  await expect(page.locator('.retrieval-snippet')).toContainText('事件独立性');
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('generator-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: '生成专属测验' }).click();
  await expect(
    page.getByRole('heading', { name: '独立事件 · 第一章巩固练习', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('已生成 2 / 2 题')).toBeVisible({ timeout: 15000 });
  const examUrl = page.url();
  await expect(page.locator('.solution')).toHaveCount(0);
  const first = page.locator('.question-card').first();
  await first.locator('.option').first().click();
  await first.getByRole('button', { name: '保存作答' }).click();
  await first.getByRole('button', { name: '查看参考答案与解析' }).click();
  await expect(first.locator('.solution .katex').first()).toBeVisible();
  await first.getByRole('spinbutton', { name: '本题自评分', exact: true }).fill('3');
  await first.getByRole('button', { name: '保存评分' }).click();
  await expect(first.getByText('自评 3 分')).toBeVisible();
  await first.getByRole('button', { name: '收藏题目', exact: true }).click();
  await expect(first.getByRole('button', { name: '取消收藏', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('exam-desktop.png'), fullPage: true });
  await page.getByRole('link', { name: '错题与收藏', exact: true }).click();
  await expect(page.locator('.question-card')).toHaveCount(1);
  await page.getByRole('button', { name: '我的收藏', exact: true }).click();
  await expect(page.locator('.question-card')).toHaveCount(1);
  await page.goto('/');
  await page.screenshot({ path: testInfo.outputPath('dashboard-desktop.png'), fullPage: true });

  const print = await context.newPage();
  await print.goto(`${examUrl}/print`);
  await expect(print.locator('.print-question')).toHaveCount(2);
  await expect(print.locator('.print-solution')).toHaveCount(0);
  await print.evaluate(() => document.fonts.ready);
  await print.pdf({
    path: testInfo.outputPath('student.pdf'),
    format: 'A4',
    preferCSSPageSize: true,
    printBackground: true,
  });
  await print.emulateMedia({ media: 'print' });
  await expect(print.locator('.sidebar')).not.toBeVisible();
  await print.screenshot({ path: testInfo.outputPath('student-print.png'), fullPage: true });
  await print.goto(`${examUrl}/print?answers=1`);
  await expect(print.locator('.print-solution')).toHaveCount(2);
  await print.evaluate(() => document.fonts.ready);
  await print.pdf({
    path: testInfo.outputPath('answers.pdf'),
    format: 'A4',
    preferCSSPageSize: true,
    printBackground: true,
  });
  await print.close();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.screenshot({ path: testInfo.outputPath('dashboard-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.goto(examUrl);
  await page
    .locator('.question-card')
    .first()
    .getByRole('button', { name: '查看参考答案与解析' })
    .click();
  await page.screenshot({ path: testInfo.outputPath('exam-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  const mobileQuestion = page.locator('.question-card').first();
  await mobileQuestion.getByRole('button', { name: '重新作答' }).click();
  await expect(mobileQuestion.locator('.solution')).toHaveCount(0);
  await expect(mobileQuestion.locator('.option.chosen')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('.question-card').first().locator('.score-badge')).toHaveCount(0);
  await page.goto('/settings');
  await expect(page.getByText('已保存 API Key')).toBeVisible();
  await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('');
  expect(pageErrors).toEqual([]);
});
