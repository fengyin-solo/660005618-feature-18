# 分布式任务工作流DAG编排与执行引擎

基于Vue 3 + FastAPI的任务编排平台，DAG拓扑排序、任务状态机、多Worker并发池、执行甘特图。

## 目标用户
数据工程师、ETL/ML Pipeline开发者、技术架构师

## 技术栈
- 前端: Vue 3 + TypeScript + Vite + Pinia + Element Plus + ECharts
- 后端: Python FastAPI + SQLite + WebSocket

## 核心功能
1. DAG工作流编辑器：拖拽添加任务节点、连线建立依赖关系、BFS拓扑排序验证环检测
2. Spring StateMachine风格任务状态机：PENDING→RUNNING→SUCCESS/FAILED/TIMEOUT
3. 多Worker并发池模拟：可配置Worker数量、任务执行耗时模拟(指数分布)
4. 任务编排策略：FIFO/优先级/最大并发三种调度策略
5. 重试机制：可配置最大重试次数、指数退避延迟
6. 执行监控：实时WebSocket推送任务状态
7. 熔断保护：连续失败阈值触发熔断，冷却时间后自动恢复
8. **只读大屏模式**：会议室投屏持续展示整条流水线进展与最近日志（详见下节）

## 只读大屏模式

普通页面 `#/` 是完整操作台；大屏是受控的只读视图，路由为 `#/screen/<房间码>`。

### 使用流程
1. operator（或任何成员）在普通页面点「📺 开始投屏」，获得 6 位房间码并打开大屏；
2. 其他成员在浏览器打开 `#/screen/<房间码>` 即可**同时观看**同一块大屏；
3. 大屏底部实时显示**投屏人**与**同屏观看**名单（心跳保活，离线自动淡出）；
4. 投屏人在普通页面点「停止投屏」：房间内所有大屏收到结束提示，普通页权限原样恢复。

### 权限模型（服务端强制，前端隐藏控件只是体验层）
身份通过 `X-Member-Id` 头传递（演示环境可在右上角切换预置成员）：

| 场景 | viewer 只读成员 | operator 普通页 | operator 投屏期间 | 大屏表面（任意角色） |
|---|---|---|---|---|
| 查看执行状态/日志 | ✅ | ✅ | ✅ | ✅ |
| 创建/执行/重跑 | ❌ 403 `viewer_readonly` | ✅ | ❌ 403 `presenting_locked` | ❌ 403 `screen_surface` |
| 结束投屏 | 仅投屏人本人 | — | — | 非本人 ❌ 403 `not_presenter` |
| 执行中重复触发 | — | 409 `already_running` | — | — |

所有拒绝响应都带 `detail.code` 与可读的中文 `detail.message`，前端直接向操作者说明理由。

### 可见范围（事先约定，两处一致）
普通页面与大屏对同一份执行共用后端唯一的只读投影（`backend/app/projection.py`），
字段约定可在页面点「字段约定」查看，或调 `GET /api/contract`（v1）：

- **run**: runId, status, workers, strategy, startedAt, finishedAt, seq
- **node**: id, name, status, retries, startTime, endTime
- **edge**: `[sourceId, targetId]`
- **log**: taskId, status, timestamp, message
- **circuitBreaker**: taskId, failureCount, state, cooldownUntil

隐藏：任务模拟耗时 `durations`、调度器内部 `will_fail/runtime` 等字段不出现在任何只读响应中。

### 实时性与韧性
- 无执行任务时大屏显示「暂无正在执行的流水线」等待提示（IDLE 空视图）；
- WS 断线自动指数退避重连（1s→15s），重连时带 `{runId, lastSeq}`：
  缺口在服务端 500 条事件环形缓冲内则逐条重放，再对齐整份快照；跨 run 或缺口过期则整份快照重放；
- 10s 心跳保活；大屏连接 30s 无心跳视为离开，投屏人断线给 60s 宽限，超时自动收档。

## 本地运行
```bash
# 后端
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev   # http://localhost:3000 （/api 与 /ws 代理到 8000）
```

## 测试
```bash
cd backend
python e2e_test.py   # 需先启动 uvicorn；33 项端到端断言（权限/投屏/WS 重连补进展/字段一致性）
```
