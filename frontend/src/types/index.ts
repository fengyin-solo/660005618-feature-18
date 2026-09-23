// 与后端 projection.py 的字段约定（CONTRACT v1）保持一致
export type TaskStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'TIMEOUT'
export type RunStatus = 'IDLE' | 'RUNNING' | 'SUCCESS' | 'FAILED'

export interface Member {
  id: string
  name: string
  role: 'operator' | 'viewer'
}

// 只读投影字段（普通页面与大屏共用，禁止直接扩展内部字段）
export interface TaskNode {
  id: string
  name: string
  status: TaskStatus
  retries: number
  startTime?: number | null
  endTime?: number | null
  // 仅 DAG 定义（创建工作流）时存在，执行投影不含坐标
  deps?: string[]
  x?: number
  y?: number
}

export interface DAGWorkflowDef { id: number; name: string; nodes: TaskNode[]; edges: [string, string][] }
export interface WorkflowRef { id: number | null; name: string | null }

export interface ExecutionLog { taskId: string; status: string; timestamp: number; message: string }
export interface CircuitBreaker { taskId: string; failureCount: number; state: string; cooldownUntil: number }

export interface RunInfo {
  runId: number | null
  status: RunStatus
  workers?: number
  strategy?: string
  startedAt?: number | null
  finishedAt?: number | null
  seq: number
}

export interface Snapshot {
  run: RunInfo | null
  status: RunStatus
  completed: boolean
  workflow: WorkflowRef | null
  nodes: TaskNode[]
  edges: [string, string][]
  logs: ExecutionLog[]
  circuitBreakers: CircuitBreaker[]
  seq: number
  runId?: number | null
}

export interface ScreenWatcher { id: string; name: string }
export interface ScreenSession {
  code: string
  status: 'active' | 'stopped' | 'expired'
  startedAt: number
  presenter: { id: string; name: string; role: string }
  presenterOnline: boolean
  watchers: ScreenWatcher[]
}

export interface FieldContract {
  version: string
  description: string
  actions: string[]
  fields: Record<string, string[]>
  hidden: string[]
}

export interface DenyDetail {
  code: 'viewer_readonly' | 'screen_surface' | 'presenting_locked' | 'not_presenter' | string
  message: string
}
