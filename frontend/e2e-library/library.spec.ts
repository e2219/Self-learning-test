import { test, expect, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';

async function register(page: Page, name: string) {
  await page.goto('http://127.0.0.1:8124');
  await page.getByRole('button', { name: '还没有账号，去注册' }).click();
  await page.getByLabel('用户名', { exact: true }).fill(name);
  await page.getByLabel('昵称', { exact: true }).fill(name);
  await page.getByLabel('密码', { exact: true }).fill('test-password-2026');
  await page.getByRole('button', { name: '注册并登录' }).click();
  await expect(page.getByRole('heading', { name: '一起积累，分别练习。' })).toBeVisible();
}

test('个人导出 → 邀请成员 → 分享修订 → 下载导入，个人成绩独立保存', async ({
  page,
  browser,
}, info) => {
  await register(page, 'owner');
  await page.getByLabel('学习库名称', { exact: true }).fill('概率论同学学习库');
  await page.getByLabel('简介', { exact: true }).fill('分享期末试卷和错题');
  await page.getByRole('button', { name: '创建学习库', exact: true }).click();
  await expect(page.locator('.invite-code')).toBeVisible();
  const code = (await page.locator('.invite-code').textContent())!;
  const local = await browser.newContext();
  const personal = await local.newPage();
  await personal.request.post('http://127.0.0.1:8123/api/login', {
    data: { code: 'browser-test-only' },
  });
  const course = await (
    await personal.request.post('http://127.0.0.1:8123/api/courses', {
      data: { name: '共享概率论' },
    })
  ).json();
  const pdf = execFileSync(
    '.venv/bin/python',
    [
      '-c',
      'from tests.test_api import sample_pdf; import sys; sys.stdout.buffer.write(sample_pdf())',
    ],
    { cwd: '..' },
  );
  const doc = await (
    await personal.request.post(`http://127.0.0.1:8123/api/courses/${course.id}/documents`, {
      multipart: { file: { name: 'source.pdf', mimeType: 'application/pdf', buffer: pdf } },
    })
  ).json();
  const created = await (
    await personal.request.post('http://127.0.0.1:8123/api/exams', {
      data: {
        course_id: course.id,
        title: '同学的概率试卷',
        ranges: [{ document_id: doc.id, start: 1, end: 1 }],
        rules: [{ type: 'choice', count: 1, points: 5 }],
      },
    })
  ).json();
  await personal.goto(`http://127.0.0.1:8123/exams/${created.id}`);
  await expect(personal.getByText('已生成 1 / 1 题')).toBeVisible();
  await personal.locator('.option').first().click();
  await personal.getByRole('button', { name: '保存作答', exact: true }).click();
  await expect(personal.getByText('得分 5 分')).toBeVisible();
  const exporting = personal.waitForEvent('download');
  await personal.getByRole('link', { name: '导出试卷包' }).click();
  const exported = await exporting;
  const buffer = await readFile((await exported.path())!);
  const pack = JSON.parse(buffer.toString());
  expect(buffer.toString()).not.toContain('user_answer');
  expect(buffer.toString()).not.toContain('document_id');
  await page
    .getByLabel('选择试卷包')
    .setInputFiles({ name: 'exam.json', mimeType: 'application/json', buffer });
  await expect(page.getByRole('heading', { name: '发布前预览' })).toBeVisible();
  await page.getByLabel('发布说明／章节考点').fill('第一章 · 独立事件');
  await page.getByRole('button', { name: '确认发布到学习库' }).click();
  await expect(page.getByRole('heading', { name: '同学的概率试卷', exact: true })).toBeVisible();
  await expect(page.locator('.katex').first()).toBeVisible();
  const peerContext = await browser.newContext();
  const peer = await peerContext.newPage();
  await register(peer, 'classmate');
  await peer.getByLabel('学习库邀请码', { exact: true }).fill(code);
  await peer.getByRole('button', { name: '加入学习库', exact: true }).click();
  await peer.getByRole('button', { name: /同学的概率试卷/ }).click();
  await expect(peer.getByRole('button', { name: '删除发布' })).toHaveCount(0);
  await peer.getByRole('button', { name: '收藏内容', exact: true }).click();
  await expect(peer.getByRole('button', { name: '取消收藏' })).toBeVisible();
  await peer.getByText('查看参考答案与解析', { exact: true }).click();
  await peer.screenshot({ path: info.outputPath('library-post-desktop.png'), fullPage: true });
  await peer.setViewportSize({ width: 390, height: 844 });
  expect(await peer.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  await peer.screenshot({ path: info.outputPath('library-post-mobile.png'), fullPage: true });
  const downloading = peer.waitForEvent('download');
  await peer.getByRole('link', { name: '下载试卷包' }).click();
  const downloaded = await downloading;
  await personal.goto('http://127.0.0.1:8123/exams');
  await personal.getByLabel('导入试卷包').setInputFiles((await downloaded.path())!);
  await expect(personal.getByText('这是导入的共享试卷。', { exact: false })).toBeVisible();
  await expect(personal.locator('.score-badge')).toHaveCount(0);
  await personal.locator('.option').nth(1).click();
  await personal.getByRole('button', { name: '保存作答', exact: true }).click();
  await expect(personal.getByText('得分 0 分')).toBeVisible();
  const original = await (
    await personal.request.get(`http://127.0.0.1:8123/api/exams/${created.id}`)
  ).json();
  expect(original.questions[0].self_score).toBe(5);
  await page.getByText('上传修订版本', { exact: true }).click();
  const revised = { ...pack, title: '修订后的概率试卷' };
  await page.getByLabel('修订试卷包', { exact: true }).setInputFiles({
    name: 'revision.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(revised)),
  });
  await page.getByRole('button', { name: '确认发布修订' }).click();
  await expect(page.getByRole('heading', { name: '修订后的概率试卷' })).toBeVisible();
  await page.getByText('修订记录（2 个版本）').click();
  await page.getByRole('button', { name: '查看版本 1' }).click();
  await expect(page.getByRole('heading', { name: '同学的概率试卷', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '概率论同学学习库', exact: true }).click();
  await page.getByText('成员与邀请码', { exact: true }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '移除成员' }).click();
  await peer.getByRole('button', { name: '概率论同学学习库', exact: true }).click();
  await expect(peer.getByText('学习库不存在或你尚未加入。')).toBeVisible();
  await peerContext.close();
  await local.close();
});

test('创建者任免管理员，管理员维护内容和成员，普通成员保留分享权限', async ({ page, browser }) => {
  await register(page, 'role_owner');
  const lib = await (
    await page.request.post('/api/libraries', {
      data: { name: '三级权限学习库', description: '成员共同维护' },
    })
  ).json();
  const adminContext = await browser.newContext();
  const memberContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const member = await memberContext.newPage();
  await register(admin, 'role_admin');
  await register(member, 'role_member');
  for (const participant of [admin, member]) {
    await participant.getByLabel('学习库邀请码', { exact: true }).fill(lib.invite_code);
    await participant.getByRole('button', { name: '加入学习库', exact: true }).click();
    await expect(participant.getByRole('heading', { name: '三级权限学习库' })).toBeVisible();
  }
  const pack = {
    format: 'zhixi-study-pack',
    version: 1,
    kind: 'exam',
    title: '成员分享的试卷',
    course: '概率论',
    questions: [
      {
        type: 'choice',
        points: 5,
        stem: '概率的最大值是多少？',
        options: ['1', '2', '3', '4'],
        answer: 'A',
        explanation: '概率不超过 1。',
        knowledge: '概率范围',
        rubric: [],
        blanks: [],
      },
    ],
  };
  const posted = await member.request.post(`/api/libraries/${lib.id}/posts`, {
    data: { pack, submission_id: 'role-member-upload', note: '' },
  });
  expect(posted.status()).toBe(201);
  const post = await posted.json();
  expect((await admin.request.get(`/api/posts/${post.id}/download`)).status()).toBe(200);
  await page.reload();
  await page.getByRole('button', { name: /三级权限学习库/ }).click();
  await page.getByText('成员与邀请码', { exact: true }).click();
  const adminRow = page.locator('.library-member').filter({ hasText: 'role_admin' });
  page.once('dialog', (dialog) => dialog.accept());
  await adminRow.getByRole('button', { name: '设为管理员', exact: true }).click();
  await expect(adminRow.getByText('role_admin · 管理员', { exact: true })).toBeVisible();
  await admin.reload();
  await admin.getByRole('button', { name: /三级权限学习库/ }).click();
  await expect(admin.getByText(/我的角色：管理员/)).toBeVisible();
  await admin.getByText('成员与邀请码', { exact: true }).click();
  await expect(admin.getByRole('button', { name: '更换邀请码' })).toBeVisible();
  await expect(admin.getByRole('button', { name: '设为管理员', exact: true })).toHaveCount(0);
  await expect(
    admin.locator('.library-member').filter({ hasText: 'role_owner' }).getByRole('button'),
  ).toHaveCount(0);
  await expect(
    admin.locator('.library-member').filter({ hasText: 'role_admin' }).getByRole('button'),
  ).toHaveCount(0);
  await admin.getByRole('button', { name: /成员分享的试卷/ }).click();
  admin.once('dialog', (dialog) => dialog.accept());
  await admin.getByRole('button', { name: '删除发布', exact: true }).click();
  await expect(admin.getByRole('button', { name: /成员分享的试卷/ })).toHaveCount(0);
  await admin.getByText('成员与邀请码', { exact: true }).click();
  admin.once('dialog', (dialog) => dialog.accept());
  await admin
    .locator('.library-member')
    .filter({ hasText: 'role_member' })
    .getByRole('button', { name: '移除成员' })
    .click();
  await expect(
    admin
      .locator('.library-member')
      .filter({ hasText: 'role_member' })
      .getByText('role_member · 已移除', { exact: true }),
  ).toBeVisible();
  expect((await member.request.get(`/api/libraries/${lib.id}`)).status()).toBe(404);
  admin.once('dialog', (dialog) => dialog.accept());
  await admin
    .locator('.library-member')
    .filter({ hasText: 'role_member' })
    .getByRole('button', { name: '恢复成员' })
    .click();
  await expect(
    admin
      .locator('.library-member')
      .filter({ hasText: 'role_member' })
      .getByText('role_member · 普通成员', { exact: true }),
  ).toBeVisible();
  expect((await member.request.get(`/api/libraries/${lib.id}`)).status()).toBe(200);
  page.once('dialog', (dialog) => dialog.accept());
  await adminRow.getByRole('button', { name: '取消管理员' }).click();
  await expect(adminRow.getByText('role_admin · 普通成员', { exact: true })).toBeVisible();
  // Existing login and stale UI cannot retain the revoked privilege.
  expect((await admin.request.post(`/api/libraries/${lib.id}/invite`)).status()).toBe(403);
  await admin.reload();
  await admin.getByRole('button', { name: /三级权限学习库/ }).click();
  await admin.getByText('成员与邀请码', { exact: true }).click();
  await expect(admin.getByRole('button', { name: '更换邀请码' })).toHaveCount(0);
  await expect(admin.getByRole('button', { name: '移除成员' })).toHaveCount(0);
  await expect(admin.getByLabel('选择试卷包')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  await adminContext.close();
  await memberContext.close();
});
