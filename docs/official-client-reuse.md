# 优先复用 Codex 官方客户端

2026-11-16 的复核结论：有可复用的官方客户端，不应继续把 PR #1526 的自写 TypeScript transport/runtime 当成唯一维护路线。优先验证“官方客户端作为依赖 + CloudCLI 界面适配”；只有官方接口覆盖不到的应用行为才自行实现。

本地分支 `local/official-client-reuse` 已接入官方 Python 客户端：隔离启动脚本默认启用桥接，原 3011 服务不变。基本审批转接、同轮 steer、原生历史读取和异常退出已通过自动测试；尚未完成真实网页与 Android 人工验收。

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
4. 验证子进程 stdout 关闭、进程仍存活时，等待中的 turn stream 立即抛出 `TransportClosedError`。
5. 通过独立进程验证审批不会自动通过，也不会阻塞其他控制请求；stdin EOF、SIGTERM、原生 stdout EOF 均清理子进程。
6. 验证原生输入管道阻塞、忽略 SIGTERM 以及 BrokenPipe 时的强制退出和子进程回收。
7. 通过 CloudCLI 的实际 TypeScript runtime → Python bridge → 官方二进制完成同轮 steer，断言只有一个 `turn/start`、一个 `turn/steer`、一个终态，最终答复为 `after steer`。
8. 验证新桥接进程读取原生历史；另一个客户端顺序续写后，保留的只读连接能重新读取新增内容。

测试使用真正的 Codex 0.166.0 二进制连接本地模拟模型服务，或官方单元测试中的模拟对象。测试 fixture 使用空的临时 home，不读取、复制或继续用户 `~/.codex` 中的登录和会话；这不是另一套实际账号 profile。验证脚本没有真实云端模型请求。实测 **95 项全部通过，耗时约 17 秒**。此外，CloudCLI 后端 754 项测试中 753 通过、1 跳过；新增的两项运行时回归覆盖断流和丢失 turn/start ACK。

执行：

```bash
bash scripts/check-official-codex-client.sh
```

需要 git、uv 和 fork 已安装的 Codex 依赖。验证环境首次安装需要网络，测试模型服务仅监听本机。脚本不启动 CloudCLI Web 服务、不写其数据库和服务发现文件。

## 具体复用与保留的边界

官方代码减少维护量，但仍需检查它和产品需求的差异：

- 官方 SDK 负责原生进程启动、原生消息读写及 RPC 响应关联。桥接原样转交通知和服务器请求，由 CloudCLI 的既有 runtime 处理会话、turn 状态、消息归一化和审批。因此，本次没有替换 CloudCLI 整个 runtime，也仍保留 Node/Python IPC transport。
- 该版本默认审批 handler 会接受命令/文件审批，且同步 handler 会占用唯一 reader。桥接绕过此路径，转交原始 request ID 等待 CloudCLI 答复；兜底 handler 明确拒绝。测试覆盖此行为，真实网页审批仍待验收。
- Python SDK 的请求等待没有通用超时。Node 继续负责 RPC 超时监督，超时和传输关闭均使运行中的任务失败并关闭该 app-server，不自动重试未知投递。**此策略会结束该进程承载的其他会话任务**，属于保守的故障隔离边界；不是自动恢复执行。
- SDK 的 buffered stdin 关闭可能被写入阻塞。桥接增加独立退出 watchdog，必要时先 terminate/kill 原生进程再回收；非远端 RPC 错误按致命传输故障退出，避免其他任务永久 busy。
- CLI 自己在部分 steer 竞争情况下会使用服务器给出的新 turn ID 重试；CloudCLI 中用户选择某轮次的队列条目时，不应无条件照搬这一策略。
- Python 辅助进程增加部署依赖。桥接使用 `_read_message`、`_request_raw`、`_write_message` 和 `_proc` 等私有接口；升级必须同时检查这些接口并重跑契约测试。官方源码未修改，也未复制成独立实现。
- 官方 SDK 不提供 CloudCLI 的多用户 Web 登录、SQLite 持久队列、跨浏览器恢复或队列编辑。它们仍属于本地产品逻辑。

本地启动脚本固定 Python 环境和官方源码提交，拒绝已修改的 SDK 源码。常规启动不拉取网络依赖；安装及验证由 `check-official-codex-client.sh` 单独完成。

## 历史同步与验收边界

CloudCLI 既有 watcher 约每 6 秒轮询原生会话文件，发送 `session_upserted`；当前页面在没有本地任务运行时重新加载历史。app-server 模式经 `thread/read` 读取同一份原生历史，不维护导入快照。本次验证了协议和数据读取链路，未完成浏览器、手机和跨网络的完整验收。

原生 Codex 会限制同一 thread 的写入者；某个 app-server 即使一轮已结束，也可能仍持有写锁。跨 CLI/CloudCLI 接续时应先结束任务并释放原客户端（停止或重启对应 app-server），不能把“历史可刷新”理解为“两个客户端可同时控制同一个任务”。本次没有复制、合并或共享会话目录。

真实云端模型验收的结果及待办边界以 [LOCAL_FORK.md](../LOCAL_FORK.md) 为准；本地模拟模型通过不能替代真实服务验收。下一步优先验收最终答复、网页审批及 Android 浏览器，再评估迁移到 3011。

官方源代码采用仓库的 [Apache-2.0 LICENSE](https://github.com/openai/codex/blob/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856/LICENSE)。本次以固定源码依赖运行，未复制修改官方实现；以后确需 vendoring 时保留原许可证、NOTICE、来源提交和改动说明。优先升级依赖，不维护没有来源记录的复制代码。
