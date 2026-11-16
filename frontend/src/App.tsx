import { lazy, Suspense, type ReactNode } from 'react';
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router';

import { AppShell } from '@/components/layout/AppShell';
import { Wordmark } from '@/components/ui/Wordmark';
import { workspaceTabs } from '@/features/registry';
import { useAuth } from '@/lib/auth';

// Route-level code splitting: the WebGL sign-in hero and each page load on demand.
const AuthLayout = lazy(() => import('@/components/layout/AuthLayout').then((m) => ({ default: m.AuthLayout })));
const LoginForm = lazy(() => import('@/features/auth/AuthForms').then((m) => ({ default: m.LoginForm })));
const RegisterForm = lazy(() => import('@/features/auth/AuthForms').then((m) => ({ default: m.RegisterForm })));
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const LibraryPage = lazy(() => import('@/pages/LibraryPage').then((m) => ({ default: m.LibraryPage })));
const DocumentPage = lazy(() => import('@/pages/DocumentPage').then((m) => ({ default: m.DocumentPage })));
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const QualityPage = lazy(() => import('@/pages/QualityPage').then((m) => ({ default: m.QualityPage })));
const StandardsPage = lazy(() => import('@/pages/StandardsPage').then((m) => ({ default: m.StandardsPage })));
const StandardDetailPage = lazy(() => import('@/pages/StandardDetailPage').then((m) => ({ default: m.StandardDetailPage })));
const CreatePage = lazy(() => import('@/pages/CreatePage').then((m) => ({ default: m.CreatePage })));
const DraftPage = lazy(() => import('@/pages/DraftPage').then((m) => ({ default: m.DraftPage })));
const PresentationsPage = lazy(() => import('@/pages/PresentationsPage').then((m) => ({ default: m.PresentationsPage })));
const ComingSoonPage = lazy(() => import('@/pages/ComingSoonPage').then((m) => ({ default: m.ComingSoonPage })));
const NotFoundPage = lazy(() => import('@/pages/ComingSoonPage').then((m) => ({ default: m.NotFoundPage })));

const page = (node: ReactNode) => <Suspense fallback={<div className="surface h-64 animate-pulse" />}>{node}</Suspense>;

function Splash() {
  return (
    <div className="grid min-h-dvh place-items-center" role="status" aria-label="Loading">
      <div className="animate-pulse">
        <Wordmark size="lg" />
      </div>
    </div>
  );
}

function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <Splash />;
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

function GuestOnly() {
  const { status } = useAuth();
  if (status === 'loading') return <Splash />;
  if (status === 'authenticated') return <Navigate to="/" replace />;
  return <Outlet />;
}

export function App() {
  return (
    <Routes>
      <Route element={<GuestOnly />}>
        <Route path="/login" element={<Suspense fallback={<Splash />}><AuthLayout><LoginForm /></AuthLayout></Suspense>} />
        <Route path="/register" element={<Suspense fallback={<Splash />}><AuthLayout><RegisterForm /></AuthLayout></Suspense>} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={page(<DashboardPage />)} />
          <Route path="documents" element={page(<LibraryPage />)} />
          <Route path="documents/:id" element={page(<DocumentPage extraTabs={workspaceTabs} />)} />
          <Route path="settings" element={page(<SettingsPage />)} />
          <Route path="standards" element={page(<StandardsPage />)} />
          <Route path="standards/:versionId" element={page(<StandardDetailPage />)} />
          <Route path="quality" element={page(<QualityPage />)} />
          <Route path="edit" element={page(<ComingSoonPage capability="edit" />)} />
          <Route path="create" element={page(<CreatePage />)} />
          <Route path="create/:draftId" element={page(<DraftPage />)} />
          <Route path="presentations" element={page(<PresentationsPage />)} />
          <Route path="*" element={page(<NotFoundPage />)} />
        </Route>
      </Route>
    </Routes>
  );
}
