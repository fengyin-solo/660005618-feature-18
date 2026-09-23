export interface TaskNode { id: string; name: string; deps: string[]; x: number; y: number; status: string; startTime?: number; endTime?: number; retries: number }
export interface DAGWorkflow { id: number; name: string; nodes: TaskNode[]; edges: [string,string][] }
export interface ExecutionLog { taskId: string; status: string; timestamp: number; message: string }
export interface CircuitBreaker { taskId: string; failureCount: number; state: string; cooldownUntil: number }
export interface ExecutionStats {
  total: number; pending: number; running: number; success: number; failed: number
  progressPercent: number; elapsedSeconds: number | null
}
export interface ExecutionInfo {
  workflow: DAGWorkflow | null
  logs: ExecutionLog[]
  circuitBreakers: CircuitBreaker[]
  completed: boolean
  phase: 'idle' | 'running' | 'completed'
  runSeq: number
  startedAt: number | null
  updatedAt: number | null
  stats: ExecutionStats
}
export interface UserInfo {
  username: string; displayName: string; role: 'operator' | 'viewer'; roleLabel: string
  scope: 'user' | 'screen'; canWrite: boolean; presentationId?: string | null
}
export interface PresenceMember { username: string; displayName: string; role: string; joinedAt: number }
export interface PresentationInfo {
  id: string
  presenter: { username: string; displayName: string }
  members: PresenceMember[]
  viewerCount: number
  startedAt: number
}
export type WsEvent =
  | { type: 'snapshot'; seq: number; data: ExecutionInfo }
  | { type: 'execution'; seq: number; data: ExecutionInfo }
  | { type: 'presence'; data: { presentation: PresentationInfo | null } }
  | { type: 'presentation_end'; data: { presentationId?: string; reason: string } }
  | { type: 'pong'; at?: number }
