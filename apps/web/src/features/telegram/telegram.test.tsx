import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui/Toast'
import { en } from '../../lib/i18n/en'
import { I18nProvider } from '../../lib/i18n'
import { ru } from '../../lib/i18n/ru'
import type { CommercialSignal, CommercialSignalDetail, TelegramBinding, TelegramStatus } from '../../lib/types'
import { SignalsPanel } from './SignalsPanel'
import { ConnectionPanel, MonitoringPanel, SetupSteps } from './TelegramSetup'

type Routes = Record<string, unknown | ((init?: RequestInit) => unknown)>

function mockApi(routes: Routes) {
  const calls: { method: string; url: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const url = input.replace('/api/v1', '')
    calls.push({ method, url, body: init?.body ? JSON.parse(init.body as string) : undefined })
    const key = `${method} ${url}`
    if (!(key in routes)) return new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: key } }), { status: 404 })
    const v = routes[key]
    const data = typeof v === 'function' ? (v as (i?: RequestInit) => unknown)(init) : v
    return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return calls
}

function wrap(ui: ReactNode, locale: 'en' | 'ru' = 'en') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <I18nProvider initial={locale}>
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <MemoryRouter>{ui}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    </I18nProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

const signal: CommercialSignal = {
  id: 's1', project_id: 'p1', category: 'CHANGE_CANDIDATE', summary: 'Card payments on checkout', status: 'OPEN',
  evidence_state: 'VALID', severity: 'HIGH', notify: true, occurrences: 3, first_seen_at: '2026-11-08T09:00:00Z',
  last_seen_at: '2026-11-08T10:00:00Z', request_id: 'r1', change_order_id: null, baseline_id: 'b1', stale_baseline: false,
  resolution_reason: null, resolved_category: null, resolved_at: null, version: 4,
}
const detail: CommercialSignalDetail = {
  ...signal,
  baseline_version: 1,
  finding: null,
  evidence: [
    { id: 'e1', message_id: 11, direction: 'INBOUND', sent_at: '2026-11-08T09:00:00Z', content_version: 1, state: 'VALID', quote: 'Please add card payments' },
    { id: 'e2', message_id: 12, direction: 'INBOUND', sent_at: '2026-11-08T09:30:00Z', content_version: 1, state: 'REVOKED', quote: null },
  ],
}
const binding: TelegramBinding = {
  status: 'READY', has_approved_baseline: true, binding_id: 'bind1', chat_id: 7770001, display_name: 'Aster Client',
  monitoring_enabled: false, version: 2, consent_at: null, last_batch: null,
  settings: { message_debounce_seconds: 120, max_batch_window_seconds: 900, max_batch_messages: 100, auto_send_messages: false,
    drafts_only: true, process_attachments: false, process_history_on_connect: false },
}

describe('i18n', () => {
  it('has a Russian translation for every new Telegram string', () => {
    const walk = (a: object, b: object, path: string[] = []) => {
      for (const [k, v] of Object.entries(a)) {
        const other = (b as Record<string, unknown>)[k]
        expect(other, [...path, k].join('.')).toBeDefined()
        if (typeof v === 'object') walk(v, other as object, [...path, k])
        else expect(String(other).trim(), [...path, k].join('.')).not.toBe('')
      }
    }
    walk(en.telegram, ru.telegram)
  })
})

describe('SetupSteps', () => {
  it('marks the first unfinished step as current', () => {
    wrap(<SetupSteps hasBaseline connected={false} bound={false} monitoring={false} />)
    const current = screen.getByText('Connect Telegram').closest('li')
    expect(current).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('Approve scope').closest('li')).not.toHaveAttribute('aria-current')
  })
})

describe('ConnectionPanel', () => {
  const unlinked: TelegramStatus = { configured: true, bot_username: 'termrail_bot', state: 'UNLINKED', connection: null, pending_link: null }

  it('creates a one-time link and offers it as an external Telegram link', async () => {
    const calls = mockApi({
      'POST /workspaces/w1/integrations/telegram/link-intents': { intent_id: 'i1', deep_link: 'https://t.me/termrail_bot?start=abc', expires_at: '2099-01-01T00:00:00Z' },
      'GET /workspaces/w1/integrations/telegram/status': unlinked,
    })
    wrap(<ConnectionPanel workspaceId="w1" status={unlinked} manage />)
    expect(screen.getByText(/@termrail_bot/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Connect Telegram' }))
    const link = await screen.findByRole('link', { name: /Open Telegram/ })
    expect(link).toHaveAttribute('href', 'https://t.me/termrail_bot?start=abc')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(calls.some((c) => c.method === 'POST')).toBe(true)
  })

  it('does not offer connecting to viewers', () => {
    wrap(<ConnectionPanel workspaceId="w1" status={unlinked} manage={false} />)
    expect(screen.queryByRole('button', { name: 'Connect Telegram' })).not.toBeInTheDocument()
  })

  it('shows bot permissions as readable labels, falling back to the raw key for unknown rights', () => {
    const connected: TelegramStatus = {
      ...unlinked, state: 'CONNECTED',
      connection: { id: 'c1', status: 'CONNECTED', is_enabled: true, telegram_username: 'owner', rights: ['can_read_messages', 'can_reply', 'can_future_right'], linked_at: '2026-11-08T09:00:00Z', revoked_at: null, last_event_at: null },
    }
    wrap(<ConnectionPanel workspaceId="w1" status={connected} manage />)
    expect(screen.getByText('Read messages, Reply to messages, can_future_right')).toBeInTheDocument()
    expect(screen.queryByText(/can_read_messages/)).not.toBeInTheDocument()
  })

  it('explains a revoked connection', () => {
    const revoked: TelegramStatus = {
      ...unlinked, state: 'ACCESS_REVOKED',
      connection: { id: 'c1', status: 'ACCESS_REVOKED', is_enabled: false, telegram_username: 'owner', rights: [], linked_at: '2026-11-08T09:00:00Z', revoked_at: '2026-11-08T10:00:00Z', last_event_at: null },
    }
    wrap(<ConnectionPanel workspaceId="w1" status={revoked} manage />)
    expect(screen.getByText(/Monitoring is paused and no messages are read/)).toBeInTheDocument()
  })
})

describe('MonitoringPanel', () => {
  it('requires the privacy confirmation before monitoring can start', async () => {
    const calls = mockApi({ 'PATCH /projects/p1/telegram/monitoring': { ...binding, status: 'MONITORING', monitoring_enabled: true } })
    wrap(<MonitoringPanel projectId="p1" binding={binding} manage />)
    const start = screen.getByRole('button', { name: 'Start monitoring' })
    expect(start).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(start)
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ enabled: true, privacy_acknowledged: true, expected_version: 2 }))
  })

  it('states that nothing is sent automatically', () => {
    wrap(<MonitoringPanel projectId="p1" binding={binding} manage />, 'ru')
    expect(screen.getAllByText(/ничего не отправляется/).length).toBeGreaterThan(0)
  })
})

describe('SignalsPanel', () => {
  it('lists cases and shows exact chat quotes, marking deleted ones as unavailable', async () => {
    mockApi({ 'GET /projects/p1/commercial-signals?status=active': [signal], 'GET /commercial-signals/s1': detail })
    wrap(<SignalsPanel projectId="p1" manage />)
    await userEvent.click(await screen.findByText('Card payments on checkout'))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Please add card payments')).toBeInTheDocument()
    expect(within(dialog).getByText('Message no longer available')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Estimate & draft change order' })).toBeInTheDocument()
  })

  it('requires a reason to dismiss and sends the expected version', async () => {
    const calls = mockApi({
      'GET /projects/p1/commercial-signals?status=active': [signal],
      'GET /commercial-signals/s1': detail,
      'POST /commercial-signals/s1/dismiss': { ...detail, status: 'DISMISSED', version: 5 },
    })
    wrap(<SignalsPanel projectId="p1" manage />)
    await userEvent.click(await screen.findByText('Card payments on checkout'))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Close case…' }))
    expect(within(dialog).getByRole('radio', { name: 'Not a commercial change' })).toBeChecked()
    const confirm = within(dialog).getByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByRole('textbox'), 'agreed in kickoff')
    await userEvent.click(confirm)
    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/dismiss'))?.body).toEqual({ expected_version: 4, reason: 'agreed in kickoff' }))
  })

  it('closes a case as in scope through the resolve endpoint', async () => {
    const calls = mockApi({
      'GET /projects/p1/commercial-signals?status=active': [signal],
      'GET /commercial-signals/s1': detail,
      'POST /commercial-signals/s1/resolve': { ...detail, status: 'RESOLVED', version: 5 },
    })
    wrap(<SignalsPanel projectId="p1" manage />)
    await userEvent.click(await screen.findByText('Card payments on checkout'))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Close case…' }))
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Covered by the approved scope' }))
    await userEvent.type(within(dialog).getByRole('textbox'), 'in SOW 2.1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/resolve'))?.body)
      .toEqual({ expected_version: 4, reason: 'in SOW 2.1', category: 'IN_SCOPE' }))
  })

  it('shows no actions to viewers', async () => {
    mockApi({ 'GET /projects/p1/commercial-signals?status=active': [signal], 'GET /commercial-signals/s1': detail })
    wrap(<SignalsPanel projectId="p1" manage={false} />)
    await userEvent.click(await screen.findByText('Card payments on checkout'))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('Please add card payments')
    expect(within(dialog).queryByRole('button', { name: 'Close case…' })).not.toBeInTheDocument()
  })

  it('shows the empty state', async () => {
    mockApi({ 'GET /projects/p1/commercial-signals?status=active': [] })
    wrap(<SignalsPanel projectId="p1" manage />)
    expect(await screen.findByText('No open cases')).toBeInTheDocument()
  })
})
