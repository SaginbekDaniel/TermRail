import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type {
  AIStatus,
  AnalysisRun,
  AuditEvent,
  ChangeOrder,
  ChangeOrderListItem,
  CommercialSignal,
  CommercialSignalDetail,
  EligibleChat,
  ClientRequest,
  DocumentVersion,
  Estimate,
  InboxItem,
  Job,
  Member,
  Overview,
  ProjectSummary,
  Rates,
  RequestListItem,
  ScopeState,
  SourceSpan,
  TelegramBinding,
  TelegramStatus,
} from './types'

const POLL_MS = 2000

export const qk = {
  overview: (ws: string) => ['overview', ws] as const,
  projects: (ws: string) => ['projects', ws] as const,
  project: (id: string) => ['project', id] as const,
  documents: (pid: string) => ['documents', pid] as const,
  spans: (docId: string) => ['spans', docId] as const,
  scope: (pid: string) => ['scope', pid] as const,
  rates: (pid: string) => ['rates', pid] as const,
  projectRequests: (pid: string) => ['requests', 'project', pid] as const,
  workspaceRequests: (ws: string) => ['requests', 'workspace', ws] as const,
  request: (id: string) => ['request', id] as const,
  estimates: (reqId: string) => ['estimates', reqId] as const,
  changeOrders: (ws: string, pid?: string) => ['changeOrders', ws, pid ?? 'all'] as const,
  changeOrder: (id: string) => ['changeOrder', id] as const,
  inbox: (ws: string) => ['inbox', ws] as const,
  projectAudit: (pid: string) => ['audit', 'project', pid] as const,
  members: (ws: string) => ['members', ws] as const,
  ai: ['ai'] as const,
  telegramStatus: (ws: string) => ['telegram', 'status', ws] as const,
  telegramChats: (ws: string) => ['telegram', 'chats', ws] as const,
  telegramBinding: (pid: string) => ['telegram', 'binding', pid] as const,
  signals: (pid: string, scope: 'active' | 'all') => ['signals', pid, scope] as const,
  signal: (id: string) => ['signal', id] as const,
}

const jobActive = (j: Job | null | undefined) => j?.status === 'QUEUED' || j?.status === 'RUNNING'
const runActive = (r: AnalysisRun | null | undefined) => r?.status === 'QUEUED' || r?.status === 'RUNNING'

export const useOverview = (ws: string) =>
  useQuery({ queryKey: qk.overview(ws), queryFn: () => api.get<Overview>(`/workspaces/${ws}/overview`) })

export const useProjects = (ws: string) =>
  useQuery({ queryKey: qk.projects(ws), queryFn: () => api.get<ProjectSummary[]>(`/projects?workspace_id=${ws}`) })

export const useProject = (id: string) =>
  // `id` is '' while the owning request is still loading; `/projects/` would redirect to the (workspace-scoped) list and 422.
  useQuery({ queryKey: qk.project(id), queryFn: () => api.get<ProjectSummary>(`/projects/${id}`), enabled: Boolean(id) })

export const useDocuments = (pid: string) =>
  useQuery({
    queryKey: qk.documents(pid),
    queryFn: () => api.get<DocumentVersion[]>(`/projects/${pid}/documents`),
    refetchInterval: (q) =>
      q.state.data?.some((d) => d.parse_status === 'PENDING' || d.parse_status === 'PARSING') ? POLL_MS : false,
  })

export const useSpans = (docId: string | null) =>
  useQuery({
    queryKey: qk.spans(docId ?? 'none'),
    queryFn: () => api.get<SourceSpan[]>(`/documents/${docId}/spans`),
    enabled: Boolean(docId),
    staleTime: Infinity, // spans are immutable
  })

export const useScope = (pid: string) =>
  useQuery({
    queryKey: qk.scope(pid),
    queryFn: () => api.get<ScopeState>(`/projects/${pid}/scope`),
    refetchInterval: (q) => (jobActive(q.state.data?.extraction_job) ? POLL_MS : false),
  })

export const useRates = (pid: string) =>
  useQuery({ queryKey: qk.rates(pid), queryFn: () => api.get<Rates>(`/projects/${pid}/rates`) })

export const useProjectRequests = (pid: string) =>
  useQuery({
    queryKey: qk.projectRequests(pid),
    queryFn: () => api.get<RequestListItem[]>(`/projects/${pid}/requests`),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'ANALYZING') ? POLL_MS : false),
  })

export const useRequest = (id: string) =>
  useQuery({
    queryKey: qk.request(id),
    queryFn: () => api.get<ClientRequest>(`/requests/${id}`),
    refetchInterval: (q) =>
      q.state.data?.status === 'ANALYZING' || runActive(q.state.data?.latest_run) ? POLL_MS : false,
  })

export const useEstimates = (reqId: string) =>
  useQuery({ queryKey: qk.estimates(reqId), queryFn: () => api.get<Estimate[]>(`/requests/${reqId}/estimates`) })

export const useChangeOrders = (ws: string, pid?: string) =>
  useQuery({
    queryKey: qk.changeOrders(ws, pid),
    queryFn: () =>
      api.get<ChangeOrderListItem[]>(`/change-orders?workspace_id=${ws}${pid ? `&project_id=${pid}` : ''}`),
  })

export const useChangeOrder = (id: string) =>
  useQuery({ queryKey: qk.changeOrder(id), queryFn: () => api.get<ChangeOrder>(`/change-orders/${id}`) })

export const useInbox = (ws: string) =>
  useQuery({ queryKey: qk.inbox(ws), queryFn: () => api.get<InboxItem[]>(`/workspaces/${ws}/inbox`) })

export const useProjectAudit = (pid: string, enabled = true) =>
  useQuery({
    queryKey: qk.projectAudit(pid),
    queryFn: () => api.get<AuditEvent[]>(`/projects/${pid}/audit`),
    enabled,
  })

export const useMembers = (ws: string) =>
  useQuery({ queryKey: qk.members(ws), queryFn: () => api.get<Member[]>(`/workspaces/${ws}/members`) })

export const useAiStatus = () =>
  useQuery({ queryKey: qk.ai, queryFn: () => api.get<AIStatus>('/system/ai'), staleTime: 60_000 })

// ---------------------------------------------------------------- Telegram
const SLOW_POLL_MS = 5000

export const useTelegramStatus = (ws: string) =>
  useQuery({
    queryKey: qk.telegramStatus(ws),
    queryFn: () => api.get<TelegramStatus>(`/workspaces/${ws}/integrations/telegram/status`),
    // While a link is in flight the user is in Telegram; reflect the handshake as soon as it lands.
    refetchInterval: (q) => (q.state.data?.state === 'LINK_PENDING' ? POLL_MS : false),
  })

export const useEligibleChats = (ws: string, enabled: boolean) =>
  useQuery({
    queryKey: qk.telegramChats(ws),
    queryFn: () => api.get<EligibleChat[]>(`/workspaces/${ws}/integrations/telegram/eligible-chats`),
    enabled,
    // Chats appear only after Telegram delivers a new message from them.
    refetchInterval: (q) => (enabled && (q.state.data?.length ?? 0) === 0 ? SLOW_POLL_MS : false),
  })

export const useTelegramBinding = (pid: string) =>
  useQuery({
    queryKey: qk.telegramBinding(pid),
    queryFn: () => api.get<TelegramBinding>(`/projects/${pid}/telegram/chat-binding`),
    refetchInterval: (q) => (q.state.data?.last_batch?.state === 'OPEN' ? SLOW_POLL_MS : false),
  })

export const useSignals = (pid: string, scope: 'active' | 'all') =>
  useQuery({
    queryKey: qk.signals(pid, scope),
    queryFn: () => api.get<CommercialSignal[]>(`/projects/${pid}/commercial-signals?status=${scope}`),
  })

export const useSignal = (id: string | null) =>
  useQuery({
    queryKey: qk.signal(id ?? 'none'),
    queryFn: () => api.get<CommercialSignalDetail>(`/commercial-signals/${id}`),
    enabled: Boolean(id),
  })
