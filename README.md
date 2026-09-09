# codex-provider-setup

任意 Provider × Codex 跨平台一键接入/管理工具（Windows / macOS / Linux）。

以官方 DeepSeek 接入脚本的成熟做法为蓝本，将其泛化：任意 OpenAI 兼容 / Responses API
兼容的模型提供方，均可通过交互菜单或一条命令行完成接入、切换、维护与回退。

## 特性

- **最小侵入、手术式改写**：只改写 `config.toml` 顶部必要的 model / model_provider /
  auth 相关字段并新增 `[model_providers.<id>]` 段；你原有的 MCP、desktop、projects、
  skills、sandbox 等配置全部保留。
- **合并式 models.json**：已存在的模型原样保留，只追加本 provider 缺失的模型；文件不
  存在时自动创建，不覆盖不清空。
- **providers-registry 持久化**：每次接入/修改写回 `providers-registry.json`，模型级参
  数（上下文窗口、自动压缩阈值等）跨重装保留。
- **`backup-<id>` 一键回退**：写入前在 `~/.codex/backup-<provider_id>/` 保留改动前
  的 config.toml / models.json 等原件，`restore` 可一键恢复接入前的状态。
- **上游 /models 同步与探活清理**：`sync` 把上游新出现的模型增量并入；`prune` 逐个发
  最小请求探测当前 Key 实际可用性，剔除 401/402/403/404 的模型（限流/5xx 视为不确定，
  不自动删除）。
- **DeepSeek 预设 + 完全自定义**：`--preset 1` 直连 DeepSeek 官方；或完全自定义任意
  provider id / base_url / 模型 / API Key。
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
codex-provider-setup restore --provider-id <id>  # 回退到该 provider 接入前的状态
codex-provider-setup sync --provider-id <id>     # 免交互：把上游 /models 新模型并入已接入的 provider
codex-provider-setup prune --provider-id <id>    # 免交互：探测并移除当前 Key 不可用的模型
```

## 跨平台说明

- 配置落盘位置遵循 Codex 惯例：`CODEX_HOME`（若设置）否则 `~/.codex`。
- 环境变量持久化：Windows 写入注册表（`setx` 语义），macOS/Linux 写入 shell rc 文件
  （`~/.zshrc` / `~/.bashrc` 等）。

## 致谢与版权

- 参考了 DeepSeek 官方 Codex 接入指南：
  https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/codex
- 内嵌的 Codex agent 提示词（`prompts/codex_instructions.txt`）源自 OpenAI Codex
  项目，遵循 Apache-2.0 许可；本仓库整体以 MIT 许可发布。
