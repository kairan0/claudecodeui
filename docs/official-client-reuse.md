# 优先复用 Codex 官方客户端

2026-11-16 的复核结论：有可复用的官方客户端，不应继续把 PR #1526 的自写 TypeScript transport/runtime 当成唯一维护路线。优先验证“官方客户端作为依赖 + CloudCLI 界面适配”；只有官方接口覆盖不到的应用行为才自行实现。

本次完成的是源码核对和可重复的兼容性验证，尚未把 CloudCLI 的正式运行路径切换到 Python，也未完成网页审批桥接。

## 核对到的官方实现

所有源码结论固定于 Codex `rust-v0.166.0`，提交 `6ff1e1ca3b30fc8b914720681fcf5fe62e95f856`，与 fork 使用的 CLI 二进制一致。

| 部分 | 官方来源 | 复用方式与边界 |
| --- | --- | --- |
| Codex 执行引擎、模型调用、工具、会话 | 已安装的 `@openai/codex@0.166.0` | 直接运行官方二进制；不复制核心实现 |
| CLI 的共享 app-server client | [Rust crate](https://github.com/openai/codex/tree/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/codex-rs/app-server-client) | CLI TUI/exec 共用，含启动、事件分发和关闭；依赖大量 Rust workspace crates，不能作为普通 npm 模块导入 |
| CLI 的 steer 行为 | [user_turn_submission.rs](https://github.com/openai/codex/blob/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/codex-rs/tui/src/app/user_turn_submission.rs) | 可参照或移植部分逻辑；与 TUI 状态强耦合，且其自动切换轮次策略与 CloudCLI 显式选择当前轮次的语义不同 |
| Python app-server client | [官方 SDK](https://github.com/openai/codex/tree/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/sdk/python) | 直接使用 `CodexClient` / `AsyncCodex`、turn handle；支持 steer、interrupt、事件路由和类型化响应，适合作为辅助进程候选 |
| TypeScript SDK | [exec.ts](https://github.com/openai/codex/blob/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/sdk/typescript/src/exec.ts) | 本版本封装 `codex exec`；没有可直接替换上述交互式 app-server client 的 steer 接口 |
| 协议类型 | `codex app-server generate-ts` | 从同版本二进制生成，优先使用官方类型而不是继续手写字段；类型生成不等于连接管理实现 |
| 回归测试 | [官方 turn controls](https://github.com/openai/codex/blob/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/sdk/python/tests/test_app_server_turn_controls.py)、[turn subscriptions](https://github.com/openai/codex/blob/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/sdk/python/tests/test_turn_subscriptions.py) | 原样运行，不复制修改成另一套协议假设 |

官方文档同样把 [app-server](https://learn.chatgpt.com/docs/app-server) 定位为富交互客户端集成接口。[SDK 文档](https://learn.chatgpt.com/docs/codex-sdk) 区分 TypeScript 与 Python 接口。本次未核验闭源桌面客户端内部代码，不以它为可搬运来源。

## 已做的验证

新增 `scripts/check-official-codex-client.sh`：

1. 获取并检查上述官方固定提交，直接加载未修改的 SDK 源码。
2. 在忽略的 `local-state/` 内创建独立 Python 环境，使用固定测试依赖。
3. 运行官方原有的 87 项测试，覆盖 steer、interrupt、流式事件、回执前事件、异步取消、请求路由。
4. 增加一个 CloudCLI 特有的回归场景：子进程 stdout 关闭、进程仍存活时，等待中的 turn stream 是否立即抛出 `TransportClosedError`。

测试使用真正的 Codex 0.166.0 二进制连接本地模拟模型服务，或官方单元测试中的模拟对象。测试 fixture 使用空的临时 home，不读取、复制或继续用户 `~/.codex` 中的登录和会话；这不是另一套实际账号 profile。没有真实云端模型请求。实测 **88 项全部通过，耗时约 4 秒**，包括上述 EOF 场景。它证明官方客户端能够处理这个原 PR 的特定故障，尚不代表 CloudCLI 已经接入修复。

执行：

```bash
bash scripts/check-official-codex-client.sh
```

需要 git、uv 和 fork 已安装的 Codex 依赖。验证环境首次安装需要网络，测试模型服务仅监听本机。脚本不启动 CloudCLI Web 服务、不写其数据库和服务发现文件。

## 为什么不能无条件整包替换

官方代码减少维护量，但仍需检查它和产品需求的差异：

- 该版本 `CodexClient._default_approval_handler` 默认接受命令/文件审批。正式桥接必须显式接入 CloudCLI 的审批响应；未收到确认时不能使用这个默认值。高层 `Codex` 构造器没有公开的 approval handler 参数，可能需要使用低层客户端并固定版本。
- Python SDK 的请求等待没有通用超时。它会在 EOF 时唤醒等待者，但如果服务保持连接却永远不返回，仍需外层监督。取消等待也不等于中断模型执行；不能把此前 turn/start 回执超时问题直接标成“已修复”。
- CLI 自己在部分 steer 竞争情况下会使用服务器给出的新 turn ID 重试；CloudCLI 中用户选择某轮次的队列条目时，不应无条件照搬这一策略。
- Python 辅助进程增加部署依赖。它省去了手写 JSON-RPC、事件分发和部分生命周期代码，但需要一层 Node/Python 调用、事件及审批转接，并验证进程退出和取消语义。
- 官方 SDK 不提供 CloudCLI 的多用户 Web 登录、SQLite 持久队列、跨浏览器恢复或队列编辑。它们仍属于本地产品逻辑。

因此，当前最值得推进的是固定版本的官方 Python SDK 辅助进程验证。直接把 Rust TUI 大段翻译成 TypeScript 会生成另一套需要同步上游的实现，维护收益较低。如果不接受 Python/Rust 辅助进程，则保留一个范围明确的 TypeScript 适配层，使用官方生成类型和官方测试作为约束。

## 后续接入边界

建议的依赖方向：CloudCLI 页面和持久队列 → 很薄的应用适配 → 官方 Python client → 官方 Codex app-server。在独立分支完成 turn、steer、interrupt、流式事件和审批转接后，用相同 fixture 对照现有实现，再进行用户账号下的真实验收。当前两个真实模型超时结果仍保留，模拟模型通过不能替代真实服务验收。

官方源代码采用仓库的 [Apache-2.0 LICENSE](https://github.com/openai/codex/blob/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/LICENSE)。本次以固定源码依赖运行，未复制修改官方实现；以后确需 vendoring 时保留原许可证、NOTICE、来源提交和改动说明。优先升级依赖，不维护没有来源记录的复制代码。
