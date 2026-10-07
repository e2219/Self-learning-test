# 知习 · AI 学习助手

从你自己的 PDF 教材出发，通过 DeepSeek 生成数学课程练习，支持在线查看、纸上作答、自行评分和试卷打印。面向个人的本科离散数学、概率论等课程学习。

**电脑运行服务，手机与电脑连接同一 Wi-Fi 后通过浏览器使用。无需租服务器。**

![学习概览](docs/images/dashboard-desktop.png)

界面截图使用端到端测试的示例课程和模拟题目，不代表真实 DeepSeek 出题质量。[查看手机练习界面](docs/images/exam-mobile.png)。

## 第一版功能

- 多课程独立资料库，PDF 上传、目录书签、按页预览和文本修正。
- 按教材、章节或 PDF 页码范围出题；自定义题型／随机搭配。
- 选择、判断、填空、计算、证明题；题量、分值、难度、用时和侧重点可调。
- DeepSeek 逐题生成答案、步骤解析、评分要点和资料来源页码。
- 后台生成进度、暂停、失败重试、重启后恢复入口；已完成题目保留。
- 单题编辑、删除、重新生成，历史试卷保存。
- 在线简短作答／纸上作答、自评分、评分历史快照、错题和收藏。
- 重新作答会清空当前答案与评分，同时保留错题标记和历史记录。
- LaTeX 公式显示；学生试卷与参考答案分别打印／保存 PDF。
- 本地 SQLite、访问口令登录、后端保存 API Key。

## 快速开始

先安装 **Python 3.11+、Node.js 22 LTS+、Git**。

```bash
git clone https://github.com/e2219/Self-learning-test.git
cd Self-learning-test
python start.py
```

macOS/Linux 若 `python` 不存在，使用 `python3 start.py`。Windows 可以使用 `py start.py`。

启动脚本会创建 `.venv`、安装依赖、构建前端并启动应用。首次启动需要联网下载依赖；以后仅在相关文件变化时重新安装或构建。

终端将显示：

- 电脑地址：`http://localhost:8000`
- 手机地址：例如 `http://192.168.1.5:8000`，以实际终端输出为准。
- 访问口令：首次随机生成，保存在本机 `data/access-code.txt`。

使用流程：

1. 浏览器打开地址，输入口令。
2. 在「应用设置」中填写自己的 DeepSeek API Key 并保存。
3. 在「我的课程」创建课程，上传 PDF，检查解析文本，必要时修正公式。
4. 点击「生成测验」，选资料和页码、题型、题量、分值与难度。
5. 生成后在线练习，或者点击「打印试卷」，在浏览器打印对话框中选择「另存为 PDF」。
6. 展开参考答案后自行评分。未满分题目进入错题本，满分后移出，也支持手动标记。

打印时建议使用 **A4、缩放 100%、关闭浏览器自带页眉和页脚**。复杂计算和证明预留纸上作答空间。

## 手机连接

电脑需要保持开机，应用终端保持运行。手机与电脑须能互相访问：

- 连接同一个 Wi-Fi，打开终端显示的局域网地址；手机不能使用 `localhost`。
- 系统防火墙需允许 Python / 8000 端口在家庭或私人网络上接收连接。
- 校园网、访客 Wi-Fi 可能开启设备隔离，即使同 Wi-Fi 也无法连接；可改用个人路由器或手机热点。
- 浏览器支持响应式阅读、简短答案输入、自评分；不是独立手机 App。

## 运行配置

可选环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 应用设置中的密钥 | 环境变量优先，不会在界面返回密钥内容 |
| `STUDY_ACCESS_CODE` | 首次随机生成 | 自定义访问口令，至少 8 个字符 |
| `STUDY_DATA_DIR` | 项目下的 `data` | 本地资料、数据库、初始口令保存位置 |
| `STUDY_PORT` | `8000` | HTTP 服务端口 |
| `STUDY_MAX_PDF_MB` | `1024` | 单份 PDF 大小上限，单位 MB（按 1024² 字节计算） |
| `STUDY_MAX_PDF_PAGES` | `2000` | 单份 PDF 页数上限 |

`.env.example` 仅用于说明环境变量，程序**不会自动加载 `.env`**。普通使用不需要创建此文件，直接在设置页配置 API 即可。

通过环境变量修改访问口令后，旧会话会在最多 7 天后失效；如需立即撤销所有会话，关闭应用后执行：

```bash
# 使用同一运行环境和 STUDY_DATA_DIR
.venv/bin/python -c "from backend import db; db.execute('DELETE FROM sessions')"
```

Windows 将 `.venv/bin/python` 替换为 `.venv\Scripts\python.exe`。

**备份**：先关闭应用，再复制整个 `data` 目录。恢复时保持相同目录结构。`data/`、`.env`、教材、密钥和学习记录均被 Git 忽略。API Key 在本机数据库中保存，数据库并未加密；请保护自己的电脑账户和备份。局域网版本使用 HTTP，不应直接暴露到公网。

## 出题与解析的边界

- **真实 API**：生产应用调用 `https://api.deepseek.com/chat/completions`，不自动回退到假题目。调用产生 DeepSeek API 费用。
- **检索**：本地按页码范围提取文本，以关键词／中文双字片段匹配和范围内抽样选择最多约 14,000 字符上下文；未使用向量数据库，不保证覆盖选中范围的所有知识点。建议一次选一个章节。
- **PDF**：支持文字型 PDF，默认每份最多 **1024 MB（1 GB）、2000 页**，可用上述环境变量调整，重启服务后生效。前端显示并遵循后端配置。文件分块保存、从磁盘文件流读取，避免应用把原文件整体读入内存；解析 PDF 对象、解压页面内容仍会消耗内存。上传时显示传输进度，完成传输后显示保存／解析状态。大型教材可能需要数分钟，请保持页面打开。框架会先把上传内容暂存到磁盘，导入期间临时目录和资料目录合计可能占用约两倍文件大小的磁盘空间。无 OCR、图像题识别。PDF 书签存在时才有章节目录。公式、上下标可能提取失真，应检查并修正。
- **页码**：全部为从 1 开始的 PDF 实际页序，不等同于印刷页码。
- **题目**：第一版为 AI 新编题；往年试卷可作为参考材料，尚未实现原题自动切分和抽取。
- **检查**：验证字段、选项、答案格式、来源页码和近似重复题干；无法保证数学结论、证明或题目难度绝对正确。模型提示中包含自查要求，但不是独立数学验证器。
- **评分**：所有题型都由用户自行评分，不提供 AI 自动批改。历史评分保存题目快照，题目重新生成后仍可回看；删除题目会一并删除对应记录。
- **失败**：已有题目逐题写入数据库；暂停会等待当前 API 调用结束。重启后未完成题目标记为失败，可手动继续。未完成试卷打印时仅输出已完成题目，并重新计算总分。
- **计量**：页面 token 数仅统计成功生成并保存的题目，格式校验失败等调用可能仍产生费用；实际账单以 DeepSeek 为准。

## 开发与验证

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q

cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

测试使用临时目录，不接触真实教材、数据库或 API Key。端到端测试明确使用 `tests/browser_server.py` 中的模拟生成函数，覆盖真实上传、解析修正、组卷界面、作答、自评分、错题、收藏、桌面／手机尺寸和分离打印。**模拟测试不代表已验证真实 DeepSeek 命题质量。**

仓库提供 [GitHub Actions 工作流模板](docs/ci-workflow.example.yml)，可在推送和 PR 时执行后端测试、前端构建和浏览器端到端测试，并保存截图及测试 PDF。**当前尚未启用自动 CI**：开发环境的 GitHub 令牌缺少 `workflow` 权限，GitHub 拒绝上传 `.github/workflows/ci.yml`。使用具有该权限的凭据，或在 GitHub 网页中将模板保存到该路径，即可启用。

当前版本已完成 22 项后端测试、浏览器完整流程和 512 MB 合成 PDF 上传验证；第一版另有 1 次真实 DeepSeek 小题调用记录，详见 [核验记录](docs/VERIFICATION.md)。

需要复现大文件上传验证时，在项目根目录执行 `.venv/bin/python scripts/verify_large_upload.py`。该脚本会生成 512 MB 合成 PDF，在独立临时数据目录和随机本机端口验证上传、保存与提取，然后自动清理，不接触个人学习记录、不调用 AI。合成文件只有 1 页内容，不能用来预测真实复杂教材的解析性能。

开发热更新：

```bash
# 终端 1，项目根目录。先运行一次 python start.py 获取口令，或设置 STUDY_ACCESS_CODE。
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
# 终端 2
cd frontend
npm run dev
```

开发时从 Vite 地址访问，`/api` 会代理到 8000。正常使用由 `run.py` 在同一端口提供 API 和构建后的前端，**只运行一个服务进程／一个 worker**。

## 目录

```text
backend/       FastAPI、SQLite、登录、PDF 解析、检索、DeepSeek 生成
frontend/src/  React + TypeScript 界面、KaTeX、响应式样式与打印布局
tests/         后端用例与显式模拟的浏览器测试服务
frontend/e2e/  Playwright 完整学习流程
docs/          已确认需求、验证说明
start.py       安装、构建与启动入口
run.py         已安装环境下直接启动
data/          本地运行数据（不提交）
```
