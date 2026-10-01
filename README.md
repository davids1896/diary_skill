# Diary Skill

从实际运行的 OpenClaw / Codex 微信日记工作流整理的可移植 skill。
核心是共同回忆和写作，不是自动转录技术日志。

入口：[daily-diary/SKILL.md](daily-diary/SKILL.md)。

## 安装

将仓库中的 `daily-diary/` 作为完整 skill 文件夹放入运行时的技能目录，例如 Codex 的
`~/.codex/skills/daily-diary/` 或 OpenClaw 工作区的 `skills/daily-diary/`。
不要覆盖已有的个性化 skill；先比较差异并合并。

安装 skill 不会自动创建任务、连接微信、读取聊天、导入认证或开放权限。
部署细节见 [deployment.md](daily-diary/references/deployment.md)。

## 包含内容

- 晚间聊天、随手记录、次日提要、补充确认、13:00 兜底封稿和历史补写。
- 第一人称、个人文风、独立的工作记录和日记、证据支持的时间线。
- 多机 Codex 与微信历史的只读采集契约、缺口和快照完整性判断。
- 现有中文 PDF 生成器的可配置版本，以及精确提交目标日期文件的发布脚本。
- 无真实个人资料的测试与样例。

采集器依赖各部署的 SSH、微信读取器和运行时会话格式，不冒充通用工具：
仓库提供接入契约，不包含当前机器专用的 Windows/多机采集代码。
微信发送使用部署已有的频道工具，不包含账号或 token。

## PDF 与发布

依赖：Python 3.10+、Bash、Git、`flock`、`sha256sum`、Pandoc、WeasyPrint、Poppler 工具
（`pdfinfo`、`pdffonts`、`pdftotext`、`pdftoppm`）及 Noto CJK 字体。
PDF 生成器从 PATH 查找程序，支持环境变量覆盖。

```bash
python3 daily-diary/scripts/generate_diary_pdf.py /path/to/diary/2026/10/2026-10-01.md

# 只生成、验证 PDF，不修改 Git，不推送；日期仅为路径示例。
DIARY_REPO=/path/to/diary bash daily-diary/scripts/publish-diary.sh 2026-10-01

# 获得发布授权后，明确开启提交和推送。
DIARY_REPO=/path/to/diary DIARY_PUBLISH=1 \
  bash daily-diary/scripts/publish-diary.sh 2026-10-01
```

发布默认目标为已有的 `origin/main`；不会创建远端、强推、改认证或修改调度器。
PDF 默认禁止访问网络资源；需要的图片应在获得授权后预先放在 Markdown 所在目录内。
生成脚本的字体、文本和非空页面检查不代替人的视觉审阅。

```bash
python3 -m unittest discover -s daily-diary/tests -v
```

## 证据边界

这是流程与工具的归档，不是现有线上服务已修复的声明。
截至整理时，线上任务的共享模型认证错误尚未在本次工作中修复。
本仓库不包含日记、聊天记录、原始对话摘录、主机地址、用户标识或密钥。
