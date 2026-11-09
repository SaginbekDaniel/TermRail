import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Outlet, RouterProvider, createBrowserRouter, useLocation } from 'react-router'
import { ButtonLink } from '../components/ui/Button'
import { EmptyState, ErrorState, LoadingBlock } from '../components/ui/Feedback'
import { ToastProvider } from '../components/ui/Toast'
import { ChangeOrdersPage, ProjectChangeOrdersTab } from '../features/change-orders/ChangeOrderList'
import { ChangeOrderPage } from '../features/change-orders/ChangeOrderPage'
import { LoginPage, RegisterPage } from '../features/auth/AuthPages'
import { InboxPage } from '../features/inbox/InboxPage'
import { CreateWorkspacePage } from '../features/onboarding/CreateWorkspacePage'
import { OverviewPage } from '../features/overview/OverviewPage'
import { ActivityTab } from '../features/projects/ActivityTab'
import { DocumentsTab } from '../features/projects/DocumentsTab'
import { DocumentViewer } from '../features/projects/DocumentViewer'
import { ProjectLayout } from '../features/projects/ProjectLayout'
import { ProjectOverviewTab } from '../features/projects/ProjectOverviewTab'
import { ProjectsPage } from '../features/projects/ProjectsPage'
import { RatesTab } from '../features/projects/RatesTab'
import { RequestReviewPage } from '../features/requests/RequestReviewPage'
import { RequestsTab } from '../features/requests/RequestsTab'
import { ScopeTab } from '../features/scope/ScopeTab'
import { TelegramTab } from '../features/telegram/TelegramTab'
import { SettingsPage } from '../features/settings/SettingsPage'
import { ApiError } from '../lib/api'
import { I18nProvider, useI18n } from '../lib/i18n'
import { SessionProvider, useSession } from '../lib/session'
import { ThemeProvider } from '../lib/theme'
import { AppShell } from './AppShell'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      // Never retry 4xx (permission/not found are final); retry transient failures twice.
      retry: (count, err) => (err instanceof ApiError && err.status >= 400 && err.status < 500 ? false : count < 2),
    },
    mutations: { retry: false },
  },
})

function RequireAuth() {
  const { status, me } = useSession()
  const location = useLocation()
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  if (status === 'loading') {
    return <div className="mx-auto max-w-3xl p-8"><LoadingBlock rows={4} /></div>
  }
  if (me && me.workspaces.length === 0) return <Navigate to="/onboarding" replace />
  return <Outlet />
}

function RequireSession() {
  const { status } = useSession()
  if (status === 'anonymous') return <Navigate to="/login" replace />
  if (status === 'loading') return <div className="mx-auto max-w-3xl p-8"><LoadingBlock rows={4} /></div>
  return <Outlet />
}

function NotFound() {
  const { t } = useI18n()
  return <EmptyState title={t('errors.NOT_FOUND')} action={<ButtonLink to="/">{t('nav.overview')}</ButtonLink>} />
}

function RouteError() {
  return <div className="mx-auto max-w-3xl p-8"><ErrorState error={null} onRetry={() => window.location.reload()} /></div>
}

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  { element: <RequireSession />, children: [{ path: '/onboarding', element: <CreateWorkspacePage /> }] },
  {
    element: <RequireAuth />,
    errorElement: <RouteError />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <OverviewPage /> },
          { path: 'projects', element: <ProjectsPage /> },
          {
            path: 'projects/:projectId',
            element: <ProjectLayout />,
            children: [
              { index: true, element: <ProjectOverviewTab /> },
              { path: 'documents', element: <DocumentsTab /> },
              { path: 'documents/:docId', element: <DocumentViewer /> },
              { path: 'scope', element: <ScopeTab /> },
              { path: 'telegram', element: <TelegramTab /> },
              { path: 'requests', element: <RequestsTab /> },
              { path: 'rates', element: <RatesTab /> },
              { path: 'change-orders', element: <ProjectChangeOrdersTab /> },
              { path: 'activity', element: <ActivityTab /> },
            ],
          },
          { path: 'requests/:requestId', element: <RequestReviewPage /> },
          { path: 'inbox', element: <InboxPage /> },
          { path: 'change-orders', element: <ChangeOrdersPage /> },
          { path: 'change-orders/:coId', element: <ChangeOrderPage /> },
          { path: 'settings', element: <SettingsPage /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
])

export function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <SessionProvider>
            <ToastProvider>
              <RouterProvider router={router} />
            </ToastProvider>
          </SessionProvider>
        </QueryClientProvider>
      </I18nProvider>
    </ThemeProvider>
  )
}
