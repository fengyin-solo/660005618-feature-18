# 分布式任务工作流DAG编排与执行引擎

基于Vue 3 + FastAPI的任务编排平台，DAG拓扑排序、任务状态机、多Worker并发池、执行甘特图。

## 目标用户
数据工程师、ETL/ML Pipeline开发者、技术架构师

## 技术栈
- 前端: Vue 3 + TypeScript + Vite + Pinia + Element Plus + ECharts
- 后端: Python FastAPI + NumPy + SQLite + WebSocket

## 核心功能
1. DAG工作流编辑器：拖拽添加任务节点、连线建立依赖关系、BFS拓扑排序验证环检测
2. Spring StateMachine风格任务状态机：PENDING→RUNNING→SUCCESS/FAILED/TIMEOUT
3. 多Worker并发池模拟：可配置Worker数量、任务执行耗时模拟(指数分布)
4. 任务编排策略：FIFO/优先级/最大并发三种调度策略
5. 重试机制：可配置最大重试次数、指数退避延迟
6. 执行监控：ECharts甘特图时间线渲染、实时WebSocket推送任务状态
7. 熔断保护：连续失败阈值触发熔断，冷却时间后自动恢复
8. 只读投屏大屏：独立只读视图投屏到会议室，多人同屏、在线名单、断线自动补进展

## 启动

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# 前端
cd frontend && npm install && npm run dev   # http://localhost:3000
```

## 权限与演示账号

| 账号 | 角色 | 能力 |
| --- | --- | --- |
| `operator` / `operator` | 可执行 | 普通页面可创建 DAG、执行/重跑、发起/结束投屏 |
| `viewer` / `viewer` | 只读成员 | 只能查看进展与日志、观看大屏，写操作被服务端拒绝并返回中文理由 |

- 投屏时服务端签发 `scope=screen` 的**大屏只读令牌**；大屏上任何执行/重跑请求一律 403（“当前是投屏大屏（只读视图）…”）；
- 结束投屏即吊销大屏令牌，普通页面的权限与操作**恢复原样、不受影响**；
- 普通页面与大屏对同一份执行走同一个只读序列化出口（见 `backend/app/visibility.py`），字段白名单可通过 `GET /api/contract` 查看，两处可见范围一致。

## 投屏大屏（`#/screen?token=...`）

- 同一时刻只允许一块活跃大屏（冲突返回 409 并说明是谁在投屏）；
- 多人可同时观看，名单区展示投屏人与全部在线成员（心跳掉线自动移除）；
- 无正在执行的任务时显示“空闲等待”提示，有执行时展示整条 DAG 进展、统计与最近日志；
- WebSocket 携带 `lastSeq`，断线指数退避自动重连，服务端回放缺失事件（缺口过大下发全量快照）；
- 投屏结束大屏收到 `presentation_end` 并展示原因。
