# codex-provider-setup

任意 Provider × Codex 跨平台一键接入/管理工具（Windows / macOS / Linux）。

以官方 DeepSeek 接入脚本的成熟做法为蓝本，将其泛化：任意 OpenAI 兼容 / Responses API
兼容的模型提供方，均可通过交互菜单或一条命令行完成接入、切换、维护与回退。

> **v0.2.1** — 新增 `doctor --fix-path`（修复**换机器/换用户名**后 `model_catalog_json`
> 断链导致的"模型列表为空"）与 `prune-models`（清理 models.json 垃圾，不动渠道）。
> 详见 [CHANGELOG.md](CHANGELOG.md)。

## 特性

- **最小侵入、手术式改写**：只改写 `config.toml` 顶部必要的 model / model_provider /
  auth 相关字段并新增 `[model_providers.<id>]` 段；你的 MCP、desktop、projects、
  skills、sandbox 等配置全部保留。
  例外（有意为之，都会在输出中逐条列出并留备份）：会移除 `[profiles]` / `profile` /
  `oss_provider` / `openai_base_url`，以及 `model_context_window`、`service_tier`、
  `base_instructions` 等会覆盖模型目录元数据的陈旧字段——它们会让 Codex 读不到新渠道的
  上下文窗口等参数。受影响的条目会打印成改动清单，可对照 `backup-<id>/manifest.txt` 查阅。
- **合并式 models.json**：已存在的模型原样保留，只追加本 provider 缺失的模型；文件不
  存在时自动创建，不覆盖不清空。
- **providers-registry 持久化**：每次接入/修改写回 `providers-registry.json`，模型级参
  数（上下文窗口、自动压缩阈值等）跨重装保留。
- **`backup-<id>` 一键回退**：写入前在 `~/.codex/backup-<provider_id>/` 保留改动前
  的 config.toml / models.json 等原件，`restore` 可一键恢复接入前的状态。
- **上游 /models 同步与探活清理**：`sync` 把上游新出现的模型增量并入；`prune` 逐个发
  最小请求探测当前 Key 实际可用性，剔除 401/402/403/404 的模型（限流/5xx 视为不确定，
  不自动删除）。
- **DeepSeek 官方 / Wolfox AI 预设 + 完全自定义**：`--preset 1` 直连 DeepSeek 官方；
  `--preset 2` 直连 Wolfox AI（https://api.wolfoxlabs.xyz）；或完全自定义任意
  provider id / base_url / 模型 / API Key。
- **`doctor` 诊断与桌面端缓存修复**：接入后 Codex 里看不到新模型或 provider 显示不对时，
  `doctor` 逐项定位原因；`doctor --fix` 备份后清理桌面端 UI 状态缓存，重启应用即生效。
- **脏数据自愈**：源 `config.toml` / `models.json` 或从网页复制的 API Key 若混入
  不可见控制字符（如 `\x16`）或 UTF-8 BOM，会在写入前自动清理，不因此中断接入。
- **纯标准库、零运行时依赖**：仅用 Python 标准库实现，安装即用。

## 运行前提

- Python 3.11+（开发/测试环境为 Python 3.13）
- 已安装 Codex CLI / ChatGPT 桌面端 / VS Code Codex 插件，且至少运行过一次
  （`~/.codex` 目录已存在）；或已设置 `CODEX_HOME`

## 安装 / 运行

仓库内直接运行（无需安装）：

```powershell
python -m codex_provider
```

pipx 安装（推荐，全局可用命令）：

```powershell
pipx install .
# 之后直接运行：
codex-provider-setup
```

## 用法

### 交互菜单

直接运行，无参数进入交互菜单：

```powershell
codex-provider-setup
```

### install（接入/更新 provider）

DeepSeek 官方预设，`--preset 1`（API Key 写入 `experimental_bearer_token`）：

```powershell
codex-provider-setup install --preset 1
```

Wolfox AI 预设（自家站，https://api.wolfoxlabs.xyz，chat 接口），`--preset 2`：

```powershell
codex-provider-setup install --preset 2
```

完全自定义（显式给出模型列表）：

```powershell
codex-provider-setup install `
  --provider-id myapi --base-url https://api.example.com/v1 `
  --api-key sk-xxxx --model-slugs "my-model-fast,my-model-pro"
```

完全自定义 + 自动拉取（不带 `--model-slugs` 且带 `--api-key` 时，自动调用
`{base_url}/models` 拉取模型并检测上下文窗口）：

```powershell
codex-provider-setup install `
  --provider-id myapi --base-url https://api.example.com/v1 --api-key sk-xxxx
```

### 其它子命令

```powershell
codex-provider-setup switch <model>              # 切换默认模型
codex-provider-setup status                      # 查看当前状态
codex-provider-setup update-key --provider-id <id>   # 换 Key（写入前先探活）
codex-provider-setup remove --provider-id <id>       # 删除某一个渠道（不影响其它渠道）
codex-provider-setup restore --provider-id <id>  # 回退到该 provider 接入前的整体快照
codex-provider-setup sync --provider-id <id>     # 免交互：把上游 /models 新模型并入已接入的 provider
codex-provider-setup prune --provider-id <id>    # 免交互：探测并移除当前 Key 不可用的模型
codex-provider-setup doctor                      # 诊断：Codex 里不显示新模型 / provider 不对
codex-provider-setup doctor --fix-path           # 换机器后修复 model_catalog_json 断链
codex-provider-setup doctor --fix                # 诊断并清理桌面端 UI 状态缓存（备份后清除）
codex-provider-setup prune-models --all          # 清理模型列表垃圾（不动渠道配置）
```

## 换 API Key / 删除渠道

渠道 = 一个 `[model_providers.<id>]` 段及其模型清单。日常维护都按**单个渠道**进行，
不会波及其它渠道：

```powershell
# 换 Key：写入前先探活；失败则不写（可用 --force 强制，--no-sync 跳过模型同步）
codex-provider-setup update-key --provider-id deepseek --api-key sk-xxxx

# 只删这一个渠道：移除该段、其独占模型、registry 条目
codex-provider-setup remove --provider-id deepseek --yes
```

交互菜单里选「1) 接入/更新 provider」再选一个**已接入**的渠道，会进入渠道子菜单：

```
1) 更新 API Key（换 Key 后自动重新同步模型）
2) 重新接入 / 更新模型清单（保留现有 Key）
3) 管理模型列表
4) 删除此渠道（只删这一个，不影响其它渠道）
5) 回退到运行脚本前的整体快照
```

换 Key 后会自动重新拉取 `/models` 并与本地清单比对：新 Key **看不到**的模型会列出来
并询问是否移除——否则它们会继续留在 Codex 的模型列表里，能选但用不了。

> **`restore` 与 `remove` 的区别**：`restore` 恢复的是**接入前的整体快照**，因此会一并
> 回退之后接入的其它渠道、以及你安装后对 `config.toml` 的任何手改。检测到会影响其它渠道时
> 会明确警告并列出受影响的渠道。只想移除一个渠道请用 `remove`。

所有破坏性操作（换 Key / 删渠道 / 切模型 / 影响其它渠道的 restore）都会先在
`~/.codex/safety-<时间戳>-<操作>/` 留一份可还原的副本。

## 换机器 / 发给别人用

`model_catalog_json` 记录的是**绝对路径**。把 `~/.codex` 里的配置直接拷到另一台机器
（或同一台机器的另一个用户名下）后，它会指向一个不存在的文件，**Codex 的模型列表会变空 /
模型无法使用**。这种情况下：

```powershell
codex-provider-setup doctor              # 会报 [X] 路径不存在
codex-provider-setup doctor --fix-path   # 改写为本机路径（只改这一行）
```

`--fix-path` 只改 `model_catalog_json` 一行，渠道配置、API Key 与其它设置逐字节保留，
改写前会留安全快照。若目标机器上还没有 `models.json`，请先在该机器上跑一次 `install`。

> 注意：**API Key 不会跟着配置走**——它要么在 `config.toml` 的
> `experimental_bearer_token` 里（随文件一起复制），要么在环境变量里（需要在目标机器上
> 重新设置）。若用 `env_key` 方式，目标机器上要重设环境变量并**重开终端**。

## 清理模型列表里的垃圾

模型列表（`models.json`）会积累一些**无法通过菜单删除**的条目：来自未登记渠道的、
以及被多个渠道共用的。清理只动 `models.json`，**渠道本身完全不受影响**：

```powershell
codex-provider-setup prune-models --all --dry-run   # 先预览
codex-provider-setup prune-models --all             # 只保留各渠道实际拥有的模型
codex-provider-setup prune-models --orphans         # 只删无渠道归属的条目
codex-provider-setup prune-models --drop a,b        # 精确删除指定模型
```

交互菜单里是 **7) 清理模型目录**：一键精简 / 只删孤儿 / 手动勾选任意模型 / 查看归属清单。
当前默认模型受保护，不会被删除。

## 接入后 Codex 里看不到新模型？

Codex 桌面端是 Electron 应用，会把**模型列表与 provider 显示**缓存在
`~/.codex/.codex-global-state.json` 里，并且只有在**完全退出后重新启动**时才会重新读取
`config.toml`。因此接入成功后请：

1. **完全退出** Codex / ChatGPT（含托盘图标，确认任务管理器里没有 `Codex.exe`）；
2. 重新打开，并**新建一个对话**（旧对话会保留它自己原来的模型）；
3. 若左下角或模型列表仍不对，运行 `codex-provider-setup doctor` 查看原因，
   再用 `doctor --fix` 清理缓存（会先备份到 `~/.codex/backup-ui-state-<时间戳>/`，可随时还原）。

`doctor` 会逐项检查：`config.toml` 能否解析、`model` / `model_provider` 是否设置、
`[model_providers.<id>]` 段与凭据是否存在、`model_catalog_json` 是否为**绝对路径**且包含默认模型、
是否有 Codex 进程正在运行（可能导致配置被覆盖）、以及桌面端缓存是否需要清理。

## 跨平台说明

- 配置落盘位置遵循 Codex 惯例：`CODEX_HOME`（若设置）否则 `~/.codex`。
- 环境变量持久化：Windows 写入注册表（`setx` 语义），macOS/Linux 写入 shell rc 文件
  （`~/.zshrc` / `~/.bashrc` 等）。

## 致谢与版权

- 参考了 DeepSeek 官方 Codex 接入指南：
  https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/codex
- 内嵌的 Codex agent 提示词（`prompts/codex_instructions.txt`）源自 OpenAI Codex
  项目，遵循 Apache-2.0 许可；本仓库整体以 MIT 许可发布。
