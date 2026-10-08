import { test, expect } from '@playwright/test';

test('通用接口与许可摘录：配置、导入、打印来源及手机导航', async ({ page }, info) => {
  await page.goto('/');
  await page.getByLabel('访问口令').fill('browser-test-only');
  await page.getByRole('button', { name: '开始学习', exact: true }).click();
  await page.getByRole('link', { name: '应用设置', exact: true }).click();
  const textPanel = page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: '出题与规划接口' }) });
  await textPanel.getByRole('checkbox').first().check();
  await textPanel.getByLabel('服务名称').fill('测试兼容服务');
  await textPanel.getByLabel('API 基地址').fill('https://text.example/v1');
  await textPanel.getByLabel('模型 ID').fill('test-model');
  await textPanel.getByLabel('此接口的 API Key').fill('test-secret');
  await textPanel.getByRole('button', { name: '保存出题接口' }).click();
  await expect(textPanel.getByText('当前：测试兼容服务 · test-model')).toBeVisible();
  await expect(textPanel.getByLabel('此接口的 API Key')).toHaveValue('');
  await page.screenshot({ path: info.outputPath('providers-desktop.png'), fullPage: true });
  await textPanel.getByRole('checkbox').first().uncheck();
  await textPanel.getByRole('button', { name: '保存出题接口' }).click();
  await expect(textPanel.getByText('当前：DeepSeek · deepseek-chat')).toBeVisible();
  const course = await (
    await page.request.post('/api/courses', { data: { name: '开放资源课程' } })
  ).json();
  await page.getByRole('link', { name: '资源检索', exact: true }).click();
  await page.getByLabel('关键词').fill('概率');
  await page.getByRole('button', { name: '检索资源', exact: true }).click();
  await page.getByRole('button', { name: '查看正文与许可' }).click();
  await expect(page.getByRole('link', { name: 'CC BY-SA 4.0', exact: true })).toBeVisible();
  await page.getByLabel('所属课程').selectOption(course.id);
  await page.getByLabel('试卷名称').fill('开放资源摘录卷');
  await page.getByLabel('题干摘录').fill('求两个独立事件同时发生的概率。');
  await page.getByLabel('参考答案').fill('概率相乘');
  await page.getByRole('checkbox').check();
  await page.screenshot({ path: info.outputPath('resources-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: '导入历史试卷（不调用 AI）' }).click();
  await expect(page.getByRole('heading', { name: '开放资源摘录卷', exact: true })).toBeVisible();
  await expect(page.locator('.external-attribution')).toContainText('CC BY-SA 4.0');
  await expect(page.getByRole('button', { name: '重新生成此题' })).toBeHidden();
  await page.getByRole('button', { name: '查看参考答案与解析' }).click();
  await expect(page.getByRole('button', { name: '补充详细解析（调用 API 并核验）' })).toBeHidden();
  const examUrl = page.url();
  await page.goto(examUrl + '/print');
  await expect(page.locator('.external-attribution')).toContainText('oldid=123');
  await expect(page.locator('.external-attribution')).toContainText('creativecommons.org');
  await page.screenshot({ path: info.outputPath('resource-print.png'), fullPage: true });
  await page.goto(examUrl + '/print?answers=1');
  await expect(page.locator('.print-footer')).toContainText('导入者整理');
  await page.goto('/resources');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('link', { name: '资源检索', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(392);
  await page.screenshot({ path: info.outputPath('resources-mobile.png'), fullPage: true });
});
