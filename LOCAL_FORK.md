# CloudCLI Codex steer 本地试验分支

评估日期：2026-11-16。结论：可以维护为隔离实验 fork；目前不建议替换现有 CloudCLI 1.37.8 服务。

同日后续已按用户要求落实**官方客户端复用优先**。分支 `local/official-client-reuse` 的隔离启动脚本默认使用未修改的官方 Python SDK，通过薄桥接接入现有 CloudCLI runtime。官方与桥接共 95 项测试通过，包括真实 Codex 二进制配合本地模拟模型的同轮 steer、CloudCLI runtime 整链路和原生历史更新；下文区分模拟模型与真实云端验收。详见 [官方客户端复用与边界](docs/official-client-reuse.md)。

这个分支针对 [上游 PR #1526](https://github.com/siteboon/claudecodeui/pull/1526) 的 Codex app-server 和消息队列进行修补。它没有实现 AgentsRoom 的 idea 工作区、任务看板或多智能体编排。队列里的“下一条提示词”也不等于通用待办管理。

## 来源与维护成本

- 本地分支：`local/codex-steer`；只配置了读取上游的 `upstream` remote，没有发布 GitHub fork。
- 固定原始 PR 分支：`pr/1526`，提交 `01bd6e5fed312dcd54aa0c99946ab31393a03046`。
- PR 基线：`272a10884a5a11e30667888318439b324895549b`；包含 app-server 前置工作，不能只摘取最后一条 steer 提交。
- 评估时上游主分支：`7943e285fc814a54d5549a34b90fac0805135a24`。
- PR 已关闭、未合并；本次没有查到关闭原因的维护者说明。
- PR 共修改 81 个文件，约增加 8,011 行、删除 743 行。与上述主分支的 `git merge-tree` 预检出现 24 条冲突记录。
- 快照的 package version 是 `1.37.3`，其中包含一些后来发布的代码；它不是完整的 1.37.8。后续版本的 Claude steer、side questions 等新功能不能假定存在。对照 [1.37.8 changelog](https://github.com/siteboon/claudecodeui/blob/v1.37.8/CHANGELOG.md)。
- Codex CLI/SDK 已一起固定为 `0.166.0`，与当前正式版依赖对齐；没有更新系统 Codex 或修改用户配置。

## 能解决什么

| 需求 | 评估结果 |
| --- | --- |
| 向正在运行的 Codex 补充指令 | 实现 `turn/steer`，本地模拟模型整链路通过；真实云端最终答复验收见下文。由 active token 和 `expectedTurnId` 约束当前轮次，只在 app-server 模式提供 |
| 原生 CLI 历史变化后更新页面 | 复用既有约 6 秒文件轮询和页面刷新机制，app-server 读取原生历史；跨客户端接续仍须释放原写入者，未完成手机人工验收 |
| 连续输入多个后续任务 | 每条独立持久化、按 FIFO 启动，支持编辑、删除和附件 |
| 把队列中间某条提前注入当前任务 | 支持，只消费指定条目；本地补丁修复了“当前任务本身来自队列”时的冲突 |
| 关闭浏览器后继续排队 | 队列由服务器处理，重新打开可恢复；服务异常退出后的不确定投递不会自动重发 |
| 断线或丢失 ACK | 浏览器查持久化 operation；确认未登记时以原 request ID 和 turn token 重发，避免重复注入 |
| Codex 权限审批 | 基础命令执行、文件修改审批桥接；不等于完整官方客户端交互 |
| idea、待办看板、多智能体协调 | 本 PR 不提供 |

详细原始设计见 [队列说明](docs/message-queue-steering.md) 和 [运行时说明](docs/codex-app-server-rollout.md)。

## 本地修补

1. 允许一个会话同时有一个正在运行的队列条目和一个 steer 投递，仍禁止重复普通派发、并发 steer 和越过未知投递。
2. 根据 provider 的终态判断队列结果，`complete(exitCode=1)` 或 interrupted 即使没有抛异常，也保留失败队头并阻止后续条目继续。
3. 定时任务中断旧任务后，等待该次 provider 调用退出再启动替代任务；等待最多 30 秒，超时报告失败而非强行启动。
4. 修复断线时 WebSocket 静默丢帧导致 steer 永久 pending；重发始终保留原操作身份。
5. 修复运行中卡片误显示“需要处理”，补齐繁体中文队列文案。
6. 为本地 fork 配置独立的服务发现文件，避免 3012 的启动/退出覆盖桌面客户端用于寻找 3011 的 marker。
7. 接入固定版本的官方 Python client，转交审批而不使用 SDK 默认自动接受行为；审批等待不占用 SDK reader。
8. 传输断开和 RPC 回执超时均传播失败终态并关闭 engine，阻止继续使用未知执行状态；已结束 run 不重复发 complete。
9. 独立 watchdog 处理原生输入管道阻塞、忽略 SIGTERM 和 BrokenPipe，避免只结束桥接而留下仍在工作的原生进程。

独立代码审查验证了上述关键路径，未发现这些补丁引入的新阻断。

## 异常恢复与剩余边界

先前隔离复现的两项缺陷已修复并加入运行时回归测试：

- **app-server 传输关闭但子进程未退出**：现在会让运行中的任务失败并关闭进程，释放 busy 状态。
- **已收到 turn/started，但 turn/start 的响应超时**：现在会停止 engine，而非丢掉追踪后让它继续。不会自动重试未知投递。此保守策略会使同一 app-server 中的其他运行任务一起失败。

其他覆盖限制：

- 工具结果主要在 `item/completed` 时显示，缺少完整的工具启动和输出增量；长命令的实时可见性较弱。
- 不支持完整的 `tool/requestUserInput` / MCP elicitation。文件审批前也缺少完整 diff 展示。
- 未整合最新主线，未完成真实浏览器端到端、文件审批和断网恢复的人工验收。
- 历史可刷新不代表能同时接管同一个任务。Codex 0.166 会保留原生写锁；从 CloudCLI 切到 CLI 续写时，任务结束后仍可能需要重启 CloudCLI 中的 Codex app-server，释放原客户端。只读历史连接不持有此写锁。
- 桥接复用官方源码但使用了私有接口，升级要重跑契约测试；部署增加 Python 依赖。当前进程回收在本机 Node 22.22.1、macOS ARM64 验证。
- 本地启动隔离 Web 数据库、端口和服务发现文件。Codex 历史、登录与配置仍来自统一的 `~/.codex`；上传目录仍使用 CloudCLI 原有的全局 `~/.cloudcli/assets`。

## 已完成验证

- 后端：754 项，753 通过、1 跳过、0 失败。用 `--test-concurrency=4` 并移除测试不应继承的 `CLAUDE_CLI_PATH`。
- 官方 SDK 与桥接：95 项全部通过，测试使用临时无登录 home、本地模拟 Responses 服务；包含实际 CloudCLI runtime 的同轮 steer、唯一终态、历史读回与外部续写后的刷新。
- 前端：110 个测试文件，762 项全部通过；包含丢帧重发、丢 ACK 恢复、查询失败不盲目重发。
- `npm run typecheck`、`npm run build`、`npm run lint`、`git diff --check` 通过。Lint 仍有警告，生产构建有 chunk size 提示。
- 本地 `127.0.0.1:3012` 短暂启动：首页和 `/api/auth/status` 均返回 200，独立数据库显示需要初次设置；检查后已停止。
- 官方桥接接入后的隔离启动复验也返回 200；启动及停止前后逐字节核对原服务 marker，未改变，实验服务已停止。
- 首次启动检查遗漏了全局服务发现文件的隔离；审查后发现该文件缺失。已通过 LaunchAgent PID 和 `/health` 核实原 3011 服务，恢复其发现文件，未重启服务。随后为 fork 配置独立 marker 并复验启动/退出，避免相互覆盖。
- **真实 Codex 最终答复验收未通过**：默认配置一次、同一配置模型 `gpt-6-astra` 的 low 推理强度一次，均在 120 秒时超时。第二次明确观察到 `initialize → thread/start → turn/start → turn/steer`，steer 收到成功回执；只有一次 turn/start，没有新建第二轮。但没有得到最终 `AFTER_STEER` 答复，故不能宣称完整 steer 用户体验已验证。当前证据不能确定是服务延迟、模型执行或协议覆盖问题；测试子进程已清理，未继续重试。
- **官方桥接路径再验收仍未通过**：同日以 `gpt-6-astra` / low 新建一次会话，仍在 120 秒超时。同轮 steer 获成功回执，但未取得最终答复。原生记录最后为 `turn_aborted: interrupted`，没有记录模型最终输出；桥接与测试进程已退出。该结果保留为未解决验收项，不把模拟模型测试通过当成云端已恢复。
- 验收脚本只新建临时会话，不继续已有工作；这些测试历史正常留在统一 Codex home。没有复制登录凭据或迁移会话数据库。

最初完整后端测试发现宿主 Claude 路径变量影响断言、缺少 ripgrep 二进制，另有一次高并行度下的定时断言失败。清理测试环境、限制并发、补齐安装后全套通过；没有为这些失败修改产品逻辑。

## 本地使用

现有 `projects/cloudcli-trial` 的 3011 服务和 LaunchAgent 没有被替换。此 fork 没有注册自动启动项。

```bash
cd /Users/kairan/Documents/KnowledgeBase/projects/cloudcli-fork
bash scripts/check-official-codex-client.sh  # 首次准备、升级后验证
bash scripts/start-local-fork.sh
```

打开 <http://127.0.0.1:3012>，完成独立的 CloudCLI 初次设置。Codex 设置选择 **app-server**，新建一个测试会话。任务运行期间提交后续消息进入队列，再选择 **Steer** 注入当前任务。试验结束按 Ctrl-C；原 3011 服务继续按原方式使用。

使用已有 Codex 登录，不复制 token、sessions 或 SQLite 状态。不要在多个客户端同时继续同一个 Codex 会话；需要复用上下文时创建 fork。CC Switch 切换账号前结束任务，再重启相关进程。

重建环境（Node 22 / 本机 macOS ARM64 已验证）：

```bash
npm ci --include=dev --ignore-scripts
npm rebuild better-sqlite3 bcrypt esbuild @vscode/ripgrep node-pty
node scripts/fix-node-pty.js
npm run build
```

这里显式安装 dev 依赖，防止宿主 `NODE_ENV=production` 漏装测试/构建工具。可选依赖按平台安装；桌面 Electron 和桌面自动化功能没有验收。

离线逻辑检查与真实验收分开运行：

```bash
env -u CLAUDE_CLI_PATH NODE_ENV=test DATABASE_PATH=/tmp/cloudcli-fork-check.db \
  TSX_TSCONFIG_PATH=server/tsconfig.json node --import tsx --test --test-concurrency=4 \
  'server/**/*.test.ts' 'server/**/*.test.js'
NODE_ENV=test npm run test:client
npm run typecheck
npm run lint
```

真实验收会使用当前模型额度，单独执行：

```bash
CLOUDCLI_CODEX_PYTHON="$PWD/local-state/official-client-venv/bin/python" \
  CLOUDCLI_CODEX_BRIDGE_SCRIPT="$PWD/scripts/codex-official-bridge.py" \
  PYTHONPATH="$PWD/local-state/codex-reference-0.166.0/sdk/python/src" \
  CLOUDCLI_SMOKE_MODEL=gpt-6-astra node scripts/smoke-codex-steer.mjs
```

## 后续维护与回退

原 PR 保留在 `pr/1526`，本地改动独立提交，便于逐项审查或迁移。补丁提交为 `29b9a38a`（依赖固定）、`6b62de16`（队列/终态/中断）、`0745a951`（前端恢复）。更新时先 `git fetch upstream`，在新的整合分支处理主线变化；不要在这个实验分支直接盲目 pull/rebase。异常恢复已补齐；待真实模型最终答复、主线功能整合和真实 UI 验收完成后，再评估替换正式服务。

`local-state/`、数据库、构建输出和依赖被忽略，不纳入提交。停止 3012 即回到只使用原服务；不要把实验数据库覆盖到 3011 的 state。此文记录技术验证结果，不代表已经建立长期自动跟踪或升级任务。

## Start new turn 独立补丁

分支 `local/start-new-turn` 在上一版可用 fork 上增加队列卡片的 **Start new turn**，与 Steer 并列：校验当前 active turn token，保留所选消息及附件，调用中断并等待旧 provider invocation 退出，然后在同一会话发送新一轮。中断失败或轮次已变化时保留队列消息；操作沿用持久化回执，重放同一请求不会再次执行。新轮一旦启动，即使模型随后失败，也不自动重发消息。收到原生 active_turn 接受事件后即确认投递并释放队列操作；新轮继续执行，所有原观看连接接收新输出。明确的 pre-turn 拒绝保留消息，缺少接受证据的失败标为未知，不自动重发。

此操作不是 `instant_interrupt` 配置，也不更改该配置。它尚未合入 `local/upstream-1.37.9-steer` 的未完成合并，未部署到 3011。

验证：后端 759 项中 758 通过、1 跳过；新增行为与界面专项通过。全套前端 765 项有 2 项失败（认证刷新断言、Markdown 5 秒超时），相同两文件在修改前基线与本补丁上串行重跑均 23 项通过；保留为并发/时序波动记录，不宣称首次全套无失败。构建通过，lint 保留既有警告。

审查临时脚本曾误继承现有服务的 DATABASE_PATH，写入 8 条测试记录；已按精确测试身份、临时项目路径及时间戳事务清理。原记录及表结构保留，3011 健康检查清理前后均为 200。本功能未部署。
