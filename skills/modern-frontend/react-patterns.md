# React Enterprise Patterns (18+)

Reference file for the `modern-frontend` skill. Covers function components with hooks, custom hooks, error boundaries, and React Router 6 with loaders.

## 2. React Enterprise Patterns (18+)

### Function Components with Hooks

```tsx
// features/users/UserList.tsx
import { useState, useMemo, useCallback } from 'react';
import { useUsers } from '../../hooks/useUsers';
import { UserCard } from '../../components/UserCard';
import { SearchInput } from '../../components/SearchInput';
import { ErrorBanner } from '../../components/ErrorBanner';
import { Skeleton } from '../../components/Skeleton';

export function UserList() {
  const { data: users, isLoading, error, refetch } = useUsers();
  const [searchTerm, setSearchTerm] = useState('');

  const filteredUsers = useMemo(() => {
    if (!users) return [];
    const term = searchTerm.toLowerCase();
    return users.filter(
      (u) => u.name.toLowerCase().includes(term) || u.email.toLowerCase().includes(term)
    );
  }, [users, searchTerm]);

  const handleSearch = useCallback((value: string) => {
    setSearchTerm(value);
  }, []);

  if (isLoading) return <Skeleton count={5} />;
  if (error) return <ErrorBanner message={error.message} onRetry={refetch} />;

  return (
    <section aria-labelledby="user-list-heading">
      <h1 id="user-list-heading">Users</h1>
      <SearchInput
        value={searchTerm}
        onChange={handleSearch}
        placeholder="Search users..."
        aria-label="Search users"
      />
      <p className="text-sm text-gray-500">{filteredUsers.length} results</p>
      <ul role="list" className="space-y-4">
        {filteredUsers.map((user) => (
          <li key={user.id}>
            <UserCard user={user} />
          </li>
        ))}
      </ul>
      {filteredUsers.length === 0 && (
        <p className="text-center text-gray-400 py-8">No users found.</p>
      )}
    </section>
  );
}
```

### Custom Hooks

```tsx
// hooks/useUsers.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { userApi, CreateUserDto, User } from '../api/userApi';

export function useUsers(page = 0, size = 20) {
  return useQuery({
    queryKey: ['users', page, size],
    queryFn: () => userApi.getAll(page, size),
    staleTime: 5 * 60 * 1000, // 5 minutes
    placeholderData: (previousData) => previousData,
  });
}

export function useUser(id: string) {
  return useQuery({
    queryKey: ['users', id],
    queryFn: () => userApi.getById(id),
    enabled: !!id,
  });
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dto: CreateUserDto) => userApi.create(dto),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
}

export function useDeleteUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => userApi.delete(id),
    onMutate: async (id) => {
      // Optimistic update — remove from cache immediately
      await queryClient.cancelQueries({ queryKey: ['users'] });
      const previous = queryClient.getQueryData<User[]>(['users']);
      queryClient.setQueryData<User[]>(['users'], (old) =>
        old?.filter((u) => u.id !== id)
      );
      return { previous };
    },
    onError: (_err, _id, context) => {
      // Rollback on error
      queryClient.setQueryData(['users'], context?.previous);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
}
```

```tsx
// hooks/useDebounce.ts — reusable debounce hook
import { useState, useEffect } from 'react';

export function useDebounce<T>(value: T, delayMs: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delayMs);
    return () => clearTimeout(timer); // cleanup on value/unmount
  }, [value, delayMs]);
  return debouncedValue;
}
```

### Error Boundaries

```tsx
// components/ErrorBoundary.tsx
import { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.props.onError?.(error, info);
    // Send to error tracking (Sentry, DataDog, etc.)
    console.error('ErrorBoundary caught:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div role="alert" className="p-6 bg-red-50 rounded-lg text-center">
            <h2 className="text-lg font-semibold text-red-800">Something went wrong</h2>
            <p className="text-red-600 mt-2">{this.state.error?.message}</p>
            <button
              className="mt-4 px-4 py-2 bg-red-600 text-white rounded"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              Try again
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
```

### React Router 6 with Loaders

```tsx
// router.tsx
import { createBrowserRouter, redirect } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { queryClient } from './lib/queryClient';
import { authService } from './services/authService';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Skeleton } from './components/Skeleton';

const Dashboard = lazy(() => import('./features/dashboard/Dashboard'));
const UserList = lazy(() => import('./features/users/UserList'));
const UserDetail = lazy(() => import('./features/users/UserDetail'));
const Login = lazy(() => import('./features/auth/Login'));

function requireAuth() {
  if (!authService.isAuthenticated()) {
    throw redirect(`/login?returnUrl=${encodeURIComponent(location.pathname)}`);
  }
  return null;
}

export const router = createBrowserRouter([
  {
    path: '/',
    errorElement: <ErrorBoundary><p>Route error</p></ErrorBoundary>,
    children: [
      { index: true, loader: () => redirect('/dashboard') },
      {
        path: 'dashboard',
        loader: requireAuth,
        element: (
          <Suspense fallback={<Skeleton count={3} />}>
            <Dashboard />
          </Suspense>
        ),
      },
      {
        path: 'users',
        loader: requireAuth,
        element: (
          <Suspense fallback={<Skeleton count={5} />}>
            <UserList />
          </Suspense>
        ),
      },
      {
        path: 'users/:id',
        loader: async ({ params }) => {
          requireAuth();
          return queryClient.ensureQueryData({
            queryKey: ['users', params.id],
            queryFn: () => fetch(`/api/v1/users/${params.id}`).then((r) => r.json()),
          });
        },
        element: (
          <Suspense fallback={<Skeleton />}>
            <UserDetail />
          </Suspense>
        ),
      },
      {
        path: 'login',
        element: (
          <Suspense fallback={<Skeleton />}>
            <Login />
          </Suspense>
        ),
      },
    ],
  },
]);
```

---

