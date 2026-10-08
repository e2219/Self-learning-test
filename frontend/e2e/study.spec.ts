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
  await page.getByRole('button', { name: '生成考点分配表' }).click();
  await expect(page.getByLabel('第 1 题考点', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '确认分配并生成测验' }).click();
  await expect(
    page.getByRole('heading', { name: '独立事件 · 第一章巩固练习', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('已生成 2 / 2 题')).toBeVisible({ timeout: 15000 });
  const examUrl = page.url();
  await expect(page.locator('.solution')).toHaveCount(0);
  const first = page.locator('.question-card').first();
  await expect(first.locator('.knowledge-label .katex')).toHaveCount(3);
  await expect(first.locator('.knowledge-label .katex-error')).toHaveCount(0);
  await first.locator('.option').first().click();
  await first.getByRole('button', { name: '保存作答' }).click();
  await first.getByRole('button', { name: '查看参考答案与解析' }).click();
  await expect(first.locator('.solution .katex').first()).toBeVisible();
  await first.getByRole('spinbutton', { name: '本题自评分', exact: true }).fill('3');
  await first.getByRole('button', { name: '保存评分' }).click();
  await expect(first.getByText('得分 3 分')).toBeVisible();
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
  await expect(mobileQuestion.locator('.knowledge-label .katex')).toHaveCount(3);
  const knowledgeBox = await mobileQuestion.locator('.knowledge-label').boundingBox();
  expect(knowledgeBox!.x + knowledgeBox!.width).toBeLessThanOrEqual(390);
  await mobileQuestion.getByRole('button', { name: '重新作答' }).click();
  await expect(mobileQuestion.locator('.solution')).toHaveCount(0);
  await expect(mobileQuestion.locator('.option.chosen')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('.question-card').first().locator('.score-badge')).toHaveCount(0);
  await page.goto('/settings');
  await expect(page.getByText('已保存 API Key')).toBeVisible();
  await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: '检查 DeepSeek 连接', exact: true }).click();
  await expect(page.getByText(/DeepSeek 连接正常（HTTP 200）/)).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test('扫描 PDF → 按页 OCR → 原图校对 → 缓存复用 → 出题，手机无溢出', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));
  await page.goto('/');
  await page.getByLabel('访问口令').fill('browser-test-only');
  await page.getByRole('button', { name: '开始学习', exact: true }).click();
  await page.getByRole('link', { name: '我的课程', exact: true }).click();
  await page.getByRole('button', { name: '添加课程', exact: true }).click();
  await page.getByLabel('课程名称').fill('扫描教材 OCR 测试');
  await page.getByRole('dialog').getByRole('button', { name: '创建课程', exact: true }).click();
  const pdf = execFileSync(
    '.venv/bin/python',
    [
      '-c',
      'from pypdf import PdfWriter; import sys,io; w=PdfWriter(); w.add_blank_page(width=595,height=842); b=io.BytesIO(); w.write(b); sys.stdout.buffer.write(b.getvalue())',
    ],
    { cwd: '..' },
  );
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: '扫描测试.pdf', mimeType: 'application/pdf', buffer: pdf });
  await expect(page.getByText('未提取到正文，请先识别扫描页')).toBeVisible();
  await page.getByRole('link', { name: '生成测验', exact: true }).click();
  await page.locator('.scope-title input').check();
  await page.getByRole('button', { name: '预览检索片段' }).click();
  await expect(page.getByText(/所选范围没有足够的可用文本/)).toBeVisible();
  await page.getByRole('button', { name: '识别所选页', exact: true }).click();
  const modal = page.getByRole('dialog');
  await expect(modal.getByLabel('识别开始页')).toHaveValue('1');
  await expect(modal.getByLabel('识别结束页')).toHaveValue('1');
  await modal.getByRole('button', { name: '开始识别', exact: true }).click();
  await expect(modal.getByText('已完成 · 第 1–1 页 · 1/1 页')).toBeVisible({ timeout: 10000 });
  await expect(modal.locator('.page-text')).toContainText('扫描页识别测试');
  await expect(modal.locator('.katex').first()).toBeVisible();
  await expect(modal.getByRole('img', { name: 'PDF 第 1 页原图' })).toBeVisible();
  expect(
    await modal
      .getByRole('img', { name: 'PDF 第 1 页原图' })
      .evaluate((img: HTMLImageElement) => img.naturalWidth),
  ).toBeGreaterThan(0);
  await page.screenshot({ path: testInfo.outputPath('ocr-desktop.png'), fullPage: true });
  await modal.getByRole('button', { name: '开始识别', exact: true }).click();
  await expect(modal.getByRole('button', { name: '第 1 页 · 复用已有内容' })).toBeVisible();
  await expect(modal.getByText('本任务累计 0 tokens')).toBeVisible();
  await expect(modal.getByText('复用已有内容，本次未调用 API')).toBeVisible();
  await expect(modal.getByText(/当前内容来自已保存的 AI 图片识别结果/)).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await modal.getByRole('button', { name: '仅重新识别当前页（调用 API）', exact: true }).click();
  await expect(modal.getByText('本任务累计 180 tokens')).toBeVisible();
  await modal.getByRole('button', { name: '修正此页内容' }).click();
  await modal
    .getByLabel('OCR 页面修正')
    .fill(
      '人工核对后的教材内容：若事件 A 与 B 相互独立，则 $P(A\\cap B)=P(A)P(B)$。注意独立与互斥的区别。',
    );
  await modal.getByRole('button', { name: '保存修正', exact: true }).click();
  await expect(modal.getByText('页面修正已保存。')).toBeVisible();
  await expect(modal.getByText(/当前内容来自手动修正/)).toBeVisible();
  await expect(modal.getByRole('button', { name: '仅重新识别当前页（调用 API）' })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath('ocr-mobile.png'), fullPage: true });
  expect(await modal.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await modal.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(page.getByText(/所选范围没有足够的可用文本/)).toHaveCount(0);
  await expect(page.getByText('1 页 · 教材 · 1 页有可用文字')).toBeVisible();
  await page.getByRole('button', { name: '预览检索片段' }).click();
  await expect(page.locator('.retrieval-snippet')).toContainText('人工核对后的教材内容');
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByLabel('选择题数量').fill('0');
  await page.getByLabel('计算题数量').fill('1');
  await page.getByRole('button', { name: '生成考点分配表' }).click();
  await expect(page.getByLabel('第 1 题考点', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '确认分配并生成测验' }).click();
  await expect(page.getByText('已生成 1 / 1 题')).toBeVisible({ timeout: 15000 });
  expect(pageErrors).toEqual([]);
});

test('表格核对 → 局部识别草稿 → 调整考点 → 填空与打印', async ({ page }, testInfo) => {
  await page.request.post('/api/login', { data: { code: 'browser-test-only' } });
  const course = await (
    await page.request.post('/api/courses', { data: { name: '表格与考点验证' } })
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
    await page.request.post(`/api/courses/${course.id}/documents`, {
      multipart: { file: { name: 'table.pdf', mimeType: 'application/pdf', buffer: pdf } },
    })
  ).json();
  const text =
    '实验结果，单位 mmol/L\n\n| 组别 | 处理前 | 处理后 |\n| --- | --- | --- |\n| A | 10 | 12 |\n| B | 20 | 22 |\n\n注：温度为 25℃。';
  await page.request.put(`/api/documents/${doc.id}/pages/1`, { data: { text } });
  await page.goto(`/courses/${course.id}`);
  await page.getByRole('button', { name: '预览与修正' }).click();
  await expect(page.getByText('此页含表格，核对前不用于出题。', { exact: false })).toBeVisible();
  await expect(page.locator('.page-text table')).toBeVisible();
  await page.getByRole('button', { name: '已对照原页核对表格' }).click();
  await expect(page.getByRole('button', { name: '撤销表格确认' })).toBeVisible();
  await page.getByText('局部高清识别（再次调用 API）', { exact: true }).click();
  await page.getByRole('button', { name: '识别选定区域' }).click();
  await expect(page.getByLabel('局部识别草稿')).toContainText('扫描页识别测试');
  expect((await (await page.request.get(`/api/documents/${doc.id}/pages/1`)).json()).text).toBe(
    text,
  );
  await page.screenshot({ path: testInfo.outputPath('table-review.png'), fullPage: true });
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.goto(`/generate?course=${course.id}`);
  await page.locator('.scope-title input').check();
  await page.getByLabel('选择题数量').fill('0');
  await page.getByLabel('计算题数量').fill('0');
  await page.getByLabel('填空题数量').fill('1');
  await page.getByRole('button', { name: '生成考点分配表' }).click();
  await expect(page.getByLabel('第 1 题考点', { exact: true })).toBeVisible();
  await page.getByLabel('第 1 题设问目标').fill('核对表头与实验数据');
  await page.screenshot({ path: testInfo.outputPath('blueprint.png'), fullPage: true });
  await page.getByRole('button', { name: '确认分配并生成测验' }).click();
  await expect(page.getByText('已生成 1 / 1 题')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.question-stem')).toContainText('____（1）');
  await expect(page.locator('.question-stem .katex')).toBeVisible();
  await expect(page.locator('.katex-error')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('fill-formula.png'), fullPage: true });
  await page.getByText(/考点覆盖情况/).click();
  await expect(page.getByText('事件独立性：分配 1 题，完成 1 题')).toBeVisible();
  await page.goto(page.url() + '/print');
  await expect(page.locator('.print-question')).toContainText('____（1）');
  await expect(page.locator('.katex-error')).toHaveCount(0);
  await expect(page.locator('.print-solution')).toHaveCount(0);
  await page.emulateMedia({ media: 'print' });
  await page.screenshot({ path: testInfo.outputPath('fill-print.png'), fullPage: true });
});

test('规划刷新恢复、草稿保存、资料变化提示及本地答案核验', async ({ page }, testInfo) => {
  await page.addInitScript(() => Object.defineProperty(crypto, 'randomUUID', { value: undefined }));
  await page.request.post('/api/login', { data: { code: 'browser-test-only' } });
  const course = await (
    await page.request.post('/api/courses', { data: { name: '草稿恢复验证' } })
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
    await page.request.post(`/api/courses/${course.id}/documents`, {
      multipart: { file: { name: 'restore.pdf', mimeType: 'application/pdf', buffer: pdf } },
    })
  ).json();
  let planningPosts = 0,
    hold = true;
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().endsWith('/api/exam-plans')) planningPosts++;
  });
  await page.route(
    /\/api\/(exam-plans\/[^/]+|courses\/[^/]+\/exam-plans\/latest)$/,
    async (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      const response = await route.fetch();
      const data = await response.json();
      await route.fulfill({ response, json: data && hold ? { ...data, status: 'running' } : data });
    },
  );
  await page.goto(`/generate?course=${course.id}`);
  await page.locator('.scope-title input').check();
  await page.getByLabel('选择题数量').fill('1');
  await page.getByLabel('判断题数量').fill('1');
  await page.getByLabel('填空题数量').fill('1');
  await page.getByLabel('计算题数量').fill('0');
  await page.getByRole('button', { name: '生成考点分配表' }).click();
  await expect(page.getByText('正在阅读资料并规划考点…')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '继续上次规划' }).click();
  await expect(page.getByLabel('填空题数量')).toHaveValue('1');
  await expect(page.getByText('正在阅读资料并规划考点…')).toBeVisible();
  expect(planningPosts).toBe(1);
  hold = false;
  await expect(page.getByLabel('第 1 题考点', { exact: true })).toBeVisible();
  await page.getByLabel('第 1 题设问目标').fill('人工保存的目标');
  await page.getByLabel('试卷名称').fill('恢复后的试卷');
  await expect(page.getByText(/本次规划累计.*已保存/)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '继续上次规划' }).click();
  await expect(page.getByLabel('试卷名称')).toHaveValue('恢复后的试卷');
  await expect(page.getByLabel('第 1 题设问目标')).toHaveValue('人工保存的目标');
  expect(planningPosts).toBe(1);
  await page.getByRole('button', { name: '查看草稿修改记录' }).click();
  await expect(page.getByText('第 1 题：人工保存的目标')).toBeVisible();
  await page.route(/\/api\/exam-plans\/[^/]+\/draft$/, (route) => route.abort());
  await page.getByLabel('试卷名称').fill('断网保留的试卷');
  await expect(page.getByText(/未保存到服务器，本机修改已保留/)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '继续上次规划' }).click();
  await expect(page.getByRole('button', { name: '恢复本机修改' })).toBeVisible();
  await page.unroute(/\/api\/exam-plans\/[^/]+\/draft$/);
  await page.getByRole('button', { name: '恢复本机修改' }).click();
  await expect(page.getByLabel('试卷名称')).toHaveValue('断网保留的试卷');
  await expect(page.getByText(/本次规划累计.*已保存/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('restored-draft.png'), fullPage: true });
  let examPosts = 0;
  await page.route('**/api/exams', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    examPosts++;
    await route.fetch(); // Simulate a created exam whose response never reaches the browser.
    await route.abort();
  });
  await page.getByRole('button', { name: '确认分配并生成测验' }).click();
  await expect(page.getByText('已生成 3 / 3 题')).toBeVisible({ timeout: 15000 });
  const examUrl = page.url();
  expect(examPosts).toBe(1);
  const created = await (
    await page.request.get(new URL(examUrl).pathname.replace('/exams/', '/api/exams/'))
  ).json();
  await page.request.patch(`/api/questions/${created.questions[2].id}/progress`, {
    data: { user_answer: '旧作答：0.2 和 0.5' },
  });
  await page.reload();
  const questions = page.locator('.question-card');
  await expect(questions.nth(2).getByText(/以前保存的整段作答：旧作答/)).toBeVisible();
  await questions.nth(0).locator('.option').first().click();
  await questions.nth(0).getByRole('button', { name: '保存作答' }).click();
  await expect(questions.nth(0).getByText('与参考答案一致', { exact: true })).toBeVisible();
  await questions.nth(1).getByRole('button', { name: '正确', exact: true }).click();
  await questions.nth(1).getByRole('button', { name: '保存作答' }).click();
  await expect(questions.nth(1).getByText('与参考答案一致', { exact: true })).toBeVisible();
  await questions.nth(2).getByLabel('第 1 空答案').fill('0.2');
  await questions.nth(2).getByRole('button', { name: '保存作答' }).click();
  await expect(questions.nth(2).getByText('第 1 空：与参考答案一致')).toBeVisible();
  await expect(questions.nth(2).getByText('第 2 空：未作答')).toBeVisible();
  await expect(questions.nth(2).getByText('得分 2.5 分')).toBeVisible();
  await questions.nth(2).getByLabel('第 2 空答案').fill('0.5');
  await questions.nth(2).getByRole('button', { name: '保存作答' }).click();
  await expect(
    questions.nth(2).getByText('作答与评分已保存：5 / 5 分', { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: '检查答案（不调用 AI）' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '采用建议分数' })).toHaveCount(0);
  await page.reload();
  await expect(questions.nth(2).getByLabel('第 1 空答案')).toHaveValue('0.2');
  await expect(questions.nth(2).getByText('得分 5 分')).toBeVisible();
  await questions.nth(2).getByRole('button', { name: '查看参考答案与解析' }).click();
  await questions.nth(2).getByLabel('本题自评分', { exact: true }).fill('4');
  await questions.nth(2).getByRole('button', { name: '保存评分', exact: true }).click();
  await expect(questions.nth(2).getByText('得分 4 分')).toBeVisible();
  await page.goto(`/generate?course=${course.id}`);
  await page.getByRole('button', { name: '继续上次规划' }).click();
  await expect(page.getByRole('link', { name: '查看已生成试卷' })).toHaveAttribute(
    'href',
    new URL(examUrl).pathname,
  );
  await expect(page.getByRole('button', { name: '确认分配并生成测验' })).toBeDisabled();
  await page.request.put(`/api/documents/${doc.id}/pages/1`, {
    data: { text: '新版本资料：独立事件乘法公式需要满足事件独立的条件。'.repeat(4) },
  });
  await page.reload();
  await page.getByRole('button', { name: '继续上次规划' }).click();
  await expect(page.getByText(/依据已变化：.*第 1 页/)).toBeVisible();
  await expect(page.getByLabel('第 1 题设问目标')).toHaveValue('人工保存的目标');
});
