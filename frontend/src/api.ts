import axios from 'axios'

const api = axios.create({ baseURL: '/' })

export interface QueryResponse {
  sql: string
  results: Record<string, unknown>[]
  tables_used: string[]
  requires_approval: boolean
  approval_reason?: string
  latency_ms: number
  timing: Record<string, number>
}

export interface ApproveResponse {
  executed: boolean
  results: Record<string, unknown>[]
  message: string
}

export interface SchemaColumn {
  name: string
  description: string
}

export interface SchemaTable {
  table_name: string
  description: string
  columns: SchemaColumn[]
}

export async function postQuery(question: string, history: {question: string, sql: string}[] = []): Promise<QueryResponse> {
  const { data } = await api.post<QueryResponse>('/api/query', { question, history })
  return data
}

export async function postQueryStream(question: string, history: {question: string, sql: string}[] = []): Promise<ReadableStream<Uint8Array>> {
  const response = await fetch('/api/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history }),
  })
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }
  
  return response.body!
}

export async function postApprove(sql: string, approved: boolean): Promise<ApproveResponse> {
  const { data } = await api.post<ApproveResponse>('/api/approve', { sql, approved })
  return data
}

export async function getSchema(): Promise<SchemaTable[]> {
  const { data } = await api.get<SchemaTable[]>('/api/schema')
  return data
}

export async function getHealth(): Promise<Record<string, unknown>> {
  const { data } = await api.get<Record<string, unknown>>('/api/health')
  return data
}
