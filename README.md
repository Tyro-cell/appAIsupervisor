# AI督学师（MVP）

一个“自驱力督学/监督/汇报”App：把学习计划拆成可执行任务块，按时提醒你打卡汇报，并给出督学反馈（可接 OpenAI 兼容接口）。

## 功能

- 计划创建：输入长期目标，AI给“合理化建议”并拆解未来7天任务块（没有 API Key 时用默认模板）。
- 今日任务：按时间段展示任务块，可手动补任务。
- 打卡汇报：提交“你做了什么 + 证据”，生成督学反馈；带“温和质疑”（可要求补证据）。
- 逾期提醒：到点未打卡会通知，最多 3 次；打卡后自动停止提醒。
- 持久化：SQLite 存在 App 数据目录，不会轻易清理。
- 导出：设置页一键导出 JSON（含计划/任务/打卡记录）。

## 本地运行（桌面）

要求：Windows 请用 Python 3.11 或 3.12（Kivy 目前对 3.13 支持不完整，会触发源码编译/依赖不匹配）。

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

如果 PowerShell 禁止激活脚本，可先执行一次：
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 中文字体（乱码/方块）

如果界面中文显示为方块/乱码，这是字体不含中文导致的。本项目会优先尝试：

- Windows：自动使用系统字体 `msyh.ttc`（微软雅黑）
- Android/iOS：优先找系统自带的 Noto/PingFang（不同机型路径可能不同）

如果你的设备仍乱码，放一个中文字体到以下任意路径即可被自动识别：
- `assets/fonts/NotoSansSC-Regular.otf`
- `fonts/NotoSansSC-Regular.otf`

## AI 接口配置

在“设置”里填：
- Base URL：`https://api.openai.com`（或你的 OpenAI 兼容网关）
- API Key：你的 key
- Model：例如 `gpt-4o-mini`

也支持环境变量：`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`。

## Android 打包（Buildozer，推荐 WSL2 / Linux）

Windows 上建议用 WSL2（Ubuntu）：

1) 安装依赖（WSL）：
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git zip unzip openjdk-17-jdk
sudo apt install -y build-essential autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake
pip install --upgrade pip
pip install buildozer
```

2) 在项目目录执行：
```bash
buildozer -v android debug
```

输出的 apk 在 `bin/` 目录。

说明：
- `buildozer.spec` 已包含 `POST_NOTIFICATIONS` 权限与一个后台 `service`（`service/main.py`），用于在 App 退到后台后继续发本地提醒（系统可能仍会因省电策略杀服务）。
- GitHub Actions 已做自动 `yes | buildozer ...` 以接受 SDK License。

## Android 在线打包（GitHub Actions）

无需本地 WSL：把项目推到 GitHub 后，用 Actions 在 Ubuntu Runner 上打包，产物直接下载 APK。

1) 把仓库推到 GitHub（建议默认分支 `main` 或 `master`）。
2) 打开 GitHub 仓库 → `Actions` → 选择 `Build Android APK (Buildozer)` → `Run workflow`。
3) 等跑完后在该次运行页面底部下载 `ai-supervisor-apk` artifact（里面是 `bin/*.apk`）。

工作流文件在：`.github/workflows/android-build.yml`。

## iOS 打包（需要 macOS）

Kivy 走 `kivy-ios`（需要 Xcode）：

1) 安装：
```bash
python3 -m pip install kivy-ios
toolchain create ai_supervisor .
toolchain build python3 kivy kivymd
toolchain open ai_supervisor
```
2) 用 Xcode 选择真机/模拟器运行与归档发布。

iOS 的后台本地提醒需要额外集成原生通知能力；本仓库先实现了“进程存活时提醒”的通用逻辑，iOS 可作为下一步增强。
