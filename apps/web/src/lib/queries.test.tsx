import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useProject } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

afterEach(() => vi.unstubAllGlobals())

describe('useProject', () => {
  // Regression: RequestReviewPage passes '' until the request loads; `/projects/` redirects to the
  // workspace-scoped list endpoint, which answers 422 (visible as a failed request on every request page).
  it('does not call the API while the project id is unknown', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useProject(''), { wrapper })
    await new Promise((r) => setTimeout(r, 20))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('fetches once the id is known', async () => {
    const fetchMock = vi.fn(async (_url: string) => new Response(JSON.stringify({ id: 'p1' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useProject('p1'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/projects/p1'), expect.anything())
  })
})
