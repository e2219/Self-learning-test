import { test, expect } from '@playwright/test';

test('通用接口配置保留，侧栏移除资源检索', async ({ page }, info) => {
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
  await expect(page.getByRole('link', { name: '资源检索', exact: true })).toHaveCount(0);
  await page.goto('/resources');
  await expect(page).toHaveURL(/\/exams$/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.sidebar nav a')).toHaveCount(5);
  await expect(page.getByRole('link', { name: '应用设置', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(392);
});

test('本地费用台账与可选计价在手机端可用', async ({ page }, info) => {
  await page.goto('/');
  await page.getByLabel('访问口令').fill('browser-test-only');
  await page.getByRole('button', { name: '开始学习', exact: true }).click();
  await page.getByRole('link', { name: '应用设置', exact: true }).click();
  await page.getByText('API 用量与参考费用', { exact: true }).click();
  await expect(page.getByText('开始日期（UTC）', { exact: false })).toBeVisible();
  await page.getByLabel('开始日期（UTC）').fill('2026-10-01');
  await page.getByRole('button', { name: '查询用量' }).click();
  await expect(page.getByText(/共 \d+ 次请求/)).toBeVisible();
  const textPanel = page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: '出题与规划接口' }) });
  await textPanel.getByRole('checkbox').first().check();
  await textPanel.getByText('思考参数与参考计价（可选）', { exact: true }).click();
  await textPanel.getByRole('combobox', { name: '思考模式', exact: true }).selectOption('disabled');
  await textPanel.getByLabel('服务名称').fill('计价测试');
  await textPanel.getByLabel('API 基地址').fill('https://text.example/v1');
  await textPanel.getByLabel('模型 ID').fill('test-model');
  await textPanel.getByLabel('此接口的 API Key').fill('test-secret');
  await textPanel.getByLabel('普通输入单价').fill('1');
  await textPanel.getByLabel('缓存命中输入单价').fill('0.1');
  await textPanel.getByLabel('输出单价').fill('2');
  await textPanel.getByRole('button', { name: '保存出题接口' }).click();
  await expect(textPanel.getByText('接口已保存。')).toBeVisible();
  await page.reload();
  await textPanel.getByText('思考参数与参考计价（可选）', { exact: true }).click();
  await expect(textPanel.getByRole('combobox', { name: '思考模式', exact: true })).toHaveValue(
    'disabled',
  );
  await expect(textPanel.getByLabel('普通输入单价')).toHaveValue('1');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByText('API 用量与参考费用', { exact: true }).click();
  await expect(page.getByRole('button', { name: '查询用量' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(392);
  await page.screenshot({ path: info.outputPath('usage-mobile.png'), fullPage: true });
});
