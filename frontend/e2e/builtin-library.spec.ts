import { test, expect } from '@playwright/test';

test('只启动个人端即可直接注册本机学习库、分享并导入，刷新后保留', async ({ page }, info) => {
  await page.request.post('/api/login', { data: { code: 'browser-test-only' } });
  const original = await (
    await page.request.post('/api/imports/study-pack', {
      data: {
        title: '本机库直用试卷',
        course: '本机测试课程',
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
    })
  ).json();
  await page.goto(`/library?share=${original.id}`);
  await expect(page.getByText('本机学习库已就绪', { exact: false })).toBeVisible();
  await expect(page.getByLabel('共享服务器地址')).toBeHidden();
  await expect(page.getByText('请先登录共享学习库。', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '还没有账号，去注册' }).click();
  await page.getByLabel('用户名', { exact: true }).fill('builtin_browser');
  await page.getByLabel('昵称', { exact: true }).fill('本机同学');
  await page.getByLabel('密码', { exact: true }).fill('builtin-browser-password');
  await page.getByRole('button', { name: '注册并登录' }).click();
  await page.getByLabel('学习库名称', { exact: true }).fill('无需连接的本机库');
  await page.getByRole('button', { name: '创建学习库', exact: true }).click();
  await page.getByRole('button', { name: '从历史试卷添加', exact: true }).click();
  await page.getByRole('button', { name: '确认发布到学习库' }).click();
  await expect(page.getByRole('heading', { name: '本机库直用试卷', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('builtin-library.png'), fullPage: true });
  await page.getByRole('button', { name: '加入我的历史试卷', exact: true }).click();
  await page.waitForURL(/\/exams\/[a-f0-9]+$/);
  expect(page.url()).not.toContain(original.id);
  await expect(page.getByText('来源位置：本机学习库')).toBeVisible();
  await page.reload();
  await page.getByRole('link', { name: '查看来源试卷' }).click();
  await expect(page.getByText('此版本已导入，不会重复创建。')).toBeVisible();
});
