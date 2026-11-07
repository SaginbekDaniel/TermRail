import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, getToken, setToken, setUnauthorizedHandler } from './api'
import type { Me, TokenOut, Workspace } from './types'

const WS_KEY = 'scopelock.workspace'

interface Session {
  status: 'anonymous' | 'loading' | 'ready'
  me: Me | null
  workspace: Workspace | null
  expired: boolean
  selectWorkspace: (id: string) => void
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<unknown>
}

const Ctx = createContext<Session | null>(null)

function storedWorkspace(): string | null {
  try {
    return localStorage.getItem(WS_KEY)
  } catch {
    return null
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [hasToken, setHasToken] = useState(() => Boolean(getToken()))
  const [expired, setExpired] = useState(false)
  const [workspaceId, setWorkspaceId] = useState<string | null>(storedWorkspace)

  const meQuery = useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<Me>('/me'),
    enabled: hasToken,
    staleTime: 60_000,
  })

  const logout = useCallback(() => {
    setToken(null)
    setHasToken(false)
    qc.clear()
  }, [qc])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setExpired(true)
      logout()
    })
    return () => setUnauthorizedHandler(null)
  }, [logout])

  const acceptToken = useCallback(
    async (t: TokenOut) => {
      setToken(t.access_token)
      setExpired(false)
      qc.clear()
      setHasToken(true)
    },
    [qc],
  )

  const login = useCallback(
    async (email: string, password: string) => acceptToken(await api.post<TokenOut>('/auth/login', { email, password })),
    [acceptToken],
  )
  const register = useCallback(
    async (email: string, password: string, displayName: string) =>
      acceptToken(await api.post<TokenOut>('/auth/register', { email, password, display_name: displayName })),
    [acceptToken],
  )

  const selectWorkspace = useCallback((id: string) => {
    setWorkspaceId(id)
    try {
      localStorage.setItem(WS_KEY, id)
    } catch {
      // ignore
    }
  }, [])

  const value = useMemo<Session>(() => {
    const me = meQuery.data ?? null
    const workspace = me ? (me.workspaces.find((w) => w.id === workspaceId) ?? me.workspaces[0] ?? null) : null
    const status: Session['status'] = !hasToken ? 'anonymous' : me ? 'ready' : 'loading'
    return { status, me, workspace, expired, selectWorkspace, login, register, logout, refresh: meQuery.refetch }
  }, [meQuery.data, meQuery.refetch, workspaceId, hasToken, expired, selectWorkspace, login, register, logout])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession(): Session {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useSession must be used inside SessionProvider')
  return ctx
}

/** The active workspace; only call inside routes guarded by RequireWorkspace. */
export function useWorkspace(): Workspace {
  const { workspace } = useSession()
  if (!workspace) throw new Error('No active workspace')
  return workspace
}

export function canManage(role: Workspace['role']): boolean {
  return role === 'OWNER' || role === 'MANAGER'
}

export function canContribute(role: Workspace['role']): boolean {
  return role !== 'VIEWER'
}
