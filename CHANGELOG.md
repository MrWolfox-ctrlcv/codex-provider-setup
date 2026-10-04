# Changelog

本文件记录本工具的显著变更。版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.2.0] - 2026-10-04

本版聚焦**渠道生命周期**：渠道 = 一个 `[model_providers.<id>]` 段及其模型清单，
现在可以独立地更换凭据、同步模型和删除，而不再波及其它渠道。

### 新增

- **更换 API Key**：`update-key` 子命令，以及交互菜单选中已接入渠道后的「更新 API Key」。
  输入不回显，**写入前先探活**；探活失败默认不写盘（`--force` 可强制，`--no-sync` 跳过模型同步）。
- **删除单个渠道**：`remove` 子命令，以及交互菜单的「删除此渠道」。只移除该渠道的
  `config.toml` 段、其独占模型条目和 registry 记录；被其它渠道共用的模型会保留。
- **换 Key 后自动重新同步模型**：重新拉取 `/models` 并对比本地清单，列出新 Key
  **已不可见**的模型并询问是否移除，避免它们继续留在 Codex 模型列表里"能选但用不了"。
- **安全快照**：所有破坏性操作（换 Key / 删渠道 / 切模型 / 会波及其它渠道的 restore）
  先在 `~/.codex/safety-<时间戳>-<操作>/` 留一份可还原副本。
- 内置 `selftest` 现在真正执行 8 项自检（此前只打印一行提示）。

### 修复

**数据安全**

- `restore` 会连带摧毁其它渠道：快照早于其它渠道的接入，恢复时会把它们一并回退。
  现在会明确列出受影响的渠道并要求确认，且执行前留安全快照。
- API Key 会随 HTTP 重定向转发到任意主机（`urllib` 默认行为只过滤 content-length /
  content-type）。已禁用重定向，`--base-url` 指向恶意或配置错误网关时不再泄漏凭据。
- `switch` 可写出非法 TOML 导致 Codex 无法解析配置，且无备份。现在校验模型名、
  写入前做 TOML 校验，并保留备份。
- 所有写入 TOML 的值改为正确转义：Key / base_url 含引号或换行不再破坏配置文件。

**交互**

- 「默认推理强度」提问的回答被直接丢弃（`model_reasoning_effort` 恒为 `high`）。
  现已接通；未传参时使用渠道自身设置。
- 上游暂时不可用时，「管理模型列表」整个菜单失效，用户无法使用本地的
  「移除模型」「编辑模型参数」。现在降级为本地模式，仅禁用需要联网的选项。
- 已接入的 `deepseek` 渠道在选择列表中被隐藏，无法被重新选中（因此其 Key 永远无法更换）。
- `prune` 对所有渠道一律请求 `/chat/completions`，对 `wire_api = "responses"` 的网关
  会把可用模型误判为不可用并删除。现在按渠道的 `wire_api` 选择端点。
- Ctrl+C 中断时会抛出 `NameError`（漏 import），显示裸栈而非干净退出。
- 非 UTF-8 的 `config.toml`（GBK/cp936 等）会直接崩溃；现在可读取并在下次保存时转为 UTF-8。
- `--preset` 为 0 时静默走自定义分支；`--preset` 与 `--provider-id` 同时给出时静默忽略后者。现在报错。
- `doctor --fix` 即使逐项失败也返回 0；`--include-web` 会把整个 Chromium 用户目录
  （数十 GB 缓存）搬进备份目录且无法用 `--restore-ui` 还原。现在只搬状态文件，缓存原地保留。
- 无法确认 Codex 是否在运行时，`--fix` 会继续移动正在使用的状态文件；现在跳过并提示。

**其它**

- 环境变量持久化会把密钥同时写入全部 4 个 rc 文件（含用户从未配置过的），覆盖同名
  `export` 且不留备份；多行值还会写坏 rc 文件。现在只改已存在的文件、写前备份、转义换行，
  并校验变量名合法性。
- CLI 路径不校验 `--provider-id` / `--base-url` / `--model-slugs` / `--env-key-name`，
  非法值会在写盘深处报出晦涩错误。现在提前校验并给出明确提示。
- 版本号在两处硬编码且已分叉（`pyproject.toml` 为 `0.1.0`，`SCRIPT_VERSION` 为 `1.1.0`）。
  现在以 `codex_provider/__init__.py` 为单一来源。

### 构建 / CI

- CI 不再"只构建不验证"：wheel 会装进干净 venv 并运行其控制台脚本，exe 会做冒烟测试，
  测试阶段也会运行内置 `selftest`。

[0.2.0]: https://github.com/MrWolfox-ctrlcv/codex-provider-setup/releases/tag/v0.2.0
