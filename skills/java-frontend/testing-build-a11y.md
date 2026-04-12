# Testing, Build/DevOps, and Accessibility

Reference file for the `java-frontend` skill. Covers testing (Jest/Testing Library, Angular testing, Playwright E2E, MSW), build tooling (Vite, Nx monorepo, GitHub Actions CI/CD, environment variables), and accessibility (WCAG 2.1 semantic HTML, keyboard navigation, color contrast, accessibility checklist).

## 9. Testing

### React — Jest + Testing Library

```tsx
// features/users/__tests__/UserList.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { UserList } from '../UserList';

const mockUsers = [
  { id: '1', name: 'Alice Smith', email: 'alice@company.com', role: 'ADMIN' },
  { id: '2', name: 'Bob Jones', email: 'bob@company.com', role: 'USER' },
];

const server = setupServer(
  http.get('/api/v1/users', () => {
    return HttpResponse.json({ content: mockUsers, totalElements: 2, totalPages: 1, page: 0 });
  })
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe('UserList', () => {
  it('renders loading state then user list', async () => {
    renderWithProviders(<UserList />);
    // Loading state shown first
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    // Users appear after fetch
    await waitFor(() => {
      expect(screen.getByText('Alice Smith')).toBeInTheDocument();
      expect(screen.getByText('Bob Jones')).toBeInTheDocument();
    });
  });

  it('filters users by search term', async () => {
    renderWithProviders(<UserList />);
    await waitFor(() => screen.getByText('Alice Smith'));
    const search = screen.getByRole('searchbox', { name: /search users/i });
    await userEvent.type(search, 'alice');
    expect(screen.getByText('Alice Smith')).toBeInTheDocument();
    expect(screen.queryByText('Bob Jones')).not.toBeInTheDocument();
    expect(screen.getByText('1 results')).toBeInTheDocument();
  });

  it('shows error banner on API failure', async () => {
    server.use(
      http.get('/api/v1/users', () => {
        return HttpResponse.json({ message: 'Server error' }, { status: 500 });
      })
    );
    renderWithProviders(<UserList />);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });
});
```

### Angular — Jasmine + Angular Testing Utilities

```typescript
// features/users/user-list/user-list.component.spec.ts
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { UserListComponent } from './user-list.component';
import { environment } from '../../../../environments/environment';

describe('UserListComponent', () => {
  let fixture: ComponentFixture<UserListComponent>;
  let component: UserListComponent;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [UserListComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(UserListComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should load and display users', () => {
    fixture.detectChanges(); // triggers ngOnInit -> loadUsers()
    const req = httpMock.expectOne(`${environment.apiUrl}/api/v1/users`);
    expect(req.request.method).toBe('GET');
    req.flush({ content: [
      { id: '1', name: 'Alice', email: 'alice@co.com' },
      { id: '2', name: 'Bob', email: 'bob@co.com' },
    ]});
    fixture.detectChanges();
    expect(component.users().length).toBe(2);
    expect(component.loading()).toBe(false);
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelectorAll('li.user-card').length).toBe(2);
  });

  it('should filter users by search term', () => {
    fixture.detectChanges();
    httpMock.expectOne(`${environment.apiUrl}/api/v1/users`).flush({
      content: [
        { id: '1', name: 'Alice', email: 'alice@co.com' },
        { id: '2', name: 'Bob', email: 'bob@co.com' },
      ],
    });
    fixture.detectChanges();
    component.searchTerm.set('alice');
    expect(component.filteredUsers().length).toBe(1);
    expect(component.filteredUsers()[0].name).toBe('Alice');
  });

  it('should display error state on failure', () => {
    fixture.detectChanges();
    httpMock.expectOne(`${environment.apiUrl}/api/v1/users`)
      .flush({ message: 'Server error' }, { status: 500, statusText: 'Internal Server Error' });
    fixture.detectChanges();
    expect(component.error()).toBeTruthy();
    expect(component.loading()).toBe(false);
    const alert = fixture.nativeElement.querySelector('[role="alert"]');
    expect(alert).toBeTruthy();
  });
});
```

### E2E — Playwright

```typescript
// e2e/users.spec.ts
import { test, expect } from '@playwright/test';

test.describe('User Management', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API responses
    await page.route('**/api/v1/users', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          content: [
            { id: '1', name: 'Alice Smith', email: 'alice@company.com', role: 'ADMIN' },
            { id: '2', name: 'Bob Jones', email: 'bob@company.com', role: 'USER' },
          ],
        }),
      });
    });
    await page.goto('/users');
  });

  test('displays user list', async ({ page }) => {
    await expect(page.getByText('Alice Smith')).toBeVisible();
    await expect(page.getByText('Bob Jones')).toBeVisible();
    await expect(page.getByText('2 results')).toBeVisible();
  });

  test('filters users via search', async ({ page }) => {
    const search = page.getByRole('searchbox', { name: /search users/i });
    await search.fill('alice');
    await expect(page.getByText('Alice Smith')).toBeVisible();
    await expect(page.getByText('Bob Jones')).not.toBeVisible();
    await expect(page.getByText('1 results')).toBeVisible();
  });

  test('handles keyboard navigation', async ({ page }) => {
    await page.keyboard.press('Tab'); // focus search
    await expect(page.getByRole('searchbox')).toBeFocused();
    await page.keyboard.type('bob');
    await expect(page.getByText('1 results')).toBeVisible();
  });
});
```

### Mock Service Worker (MSW) Setup

```typescript
// mocks/handlers.ts — shared between tests and dev server
import { http, HttpResponse } from 'msw';

export const handlers = [
  http.get('/api/v1/users', ({ request }) => {
    const url = new URL(request.url);
    const page = Number(url.searchParams.get('page') ?? 0);
    return HttpResponse.json({
      content: [
        { id: '1', name: 'Alice Smith', email: 'alice@company.com', role: 'ADMIN' },
        { id: '2', name: 'Bob Jones', email: 'bob@company.com', role: 'USER' },
      ],
      totalElements: 2,
      totalPages: 1,
      page,
    });
  }),

  http.post('/api/v1/users', async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({ id: crypto.randomUUID(), ...body }, { status: 201 });
  }),

  http.delete('/api/v1/users/:id', () => {
    return new HttpResponse(null, { status: 204 });
  }),
];
```

```typescript
// mocks/browser.ts — for development
import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';
export const worker = setupWorker(...handlers);

// main.tsx — start MSW in development
if (import.meta.env.DEV) {
  const { worker } = await import('./mocks/browser');
  await worker.start({ onUnhandledRequest: 'bypass' });
}
```

---

## 10. Build and DevOps

### Vite Configuration

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tsconfigPaths from 'vite-tsconfig-paths';

export default defineConfig(({ mode }) => ({
  plugins: [react(), tsconfigPaths()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'es2022',
    sourcemap: mode === 'production' ? 'hidden' : true, // hidden = no //# sourceMappingURL
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
          ui: ['@headlessui/react', '@heroicons/react'],
        },
      },
    },
    chunkSizeWarningLimit: 500,
  },
  define: {
    'import.meta.env.BUILD_TIME': JSON.stringify(new Date().toISOString()),
  },
}));
```

### Monorepo — Nx

```bash
# Create Nx workspace
npx create-nx-workspace@latest my-org --preset=apps

# Add Angular app
nx g @nx/angular:application portal

# Add React app
nx g @nx/react:application dashboard

# Add shared library
nx g @nx/js:library shared-types --directory=libs/shared-types
nx g @nx/js:library ui-components --directory=libs/ui-components

# Run affected tests only (CI optimization)
nx affected --target=test --base=origin/main
nx affected --target=build --base=origin/main
nx affected --target=lint --base=origin/main

# Visualize dependency graph
nx graph
```

### CI/CD Pipeline — GitHub Actions

```yaml
# .github/workflows/frontend-ci.yml
name: Frontend CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

concurrency:
  group: frontend-${{ github.ref }}
  cancel-in-progress: true

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck        # tsc --noEmit
      - run: npm run test -- --ci --coverage
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
          retention-days: 7

  e2e:
    needs: quality
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
      - run: npm ci
      - run: npx playwright install --with-deps chromium
      - run: npm run e2e
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 7

  deploy:
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    needs: [quality, e2e]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      # Deploy to CDN, S3, Azure Static Web Apps, etc.
```

### Environment Variables

```bash
# .env.development
VITE_API_URL=http://localhost:8080
VITE_OIDC_ISSUER=http://localhost:8180/realms/dev
VITE_OIDC_CLIENT_ID=frontend-dev
VITE_ENABLE_MSW=true

# .env.production
VITE_API_URL=https://api.example.com
VITE_OIDC_ISSUER=https://auth.example.com/realms/prod
VITE_OIDC_CLIENT_ID=frontend-prod
VITE_ENABLE_MSW=false
```

```typescript
// lib/env.ts — typed environment access
const env = {
  apiUrl: import.meta.env.VITE_API_URL as string,
  oidcIssuer: import.meta.env.VITE_OIDC_ISSUER as string,
  oidcClientId: import.meta.env.VITE_OIDC_CLIENT_ID as string,
  enableMsw: import.meta.env.VITE_ENABLE_MSW === 'true',
  isProd: import.meta.env.PROD,
  isDev: import.meta.env.DEV,
} as const;

// Validate required vars at startup
const required = ['apiUrl', 'oidcIssuer', 'oidcClientId'] as const;
for (const key of required) {
  if (!env[key]) throw new Error(`Missing required env var: VITE_${key.replace(/([A-Z])/g, '_$1').toUpperCase()}`);
}

export { env };
```

---

## 11. Accessibility (WCAG 2.1)

### Semantic HTML First

```tsx
// BAD — div soup with ARIA repairs
<div role="navigation" aria-label="Main">
  <div role="list">
    <div role="listitem">
      <div role="link" tabIndex={0} onClick={navigate} onKeyDown={handleKeyDown}>
        Dashboard
      </div>
    </div>
  </div>
</div>

// GOOD — semantic HTML, zero ARIA needed
<nav aria-label="Main">
  <ul>
    <li>
      <a href="/dashboard">Dashboard</a>
    </li>
  </ul>
</nav>
```

### Keyboard Navigation and Focus Management

```tsx
// hooks/useFocusTrap.ts — trap focus in modals/dialogs
import { useEffect, useRef } from 'react';

export function useFocusTrap<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusableElements = element.querySelectorAll<HTMLElement>(focusableSelector);
    const first = focusableElements[0];
    const last = focusableElements[focusableElements.length - 1];

    // Focus first element on mount
    first?.focus();

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Tab') return;
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }

    element.addEventListener('keydown', handleKeyDown);
    return () => element.removeEventListener('keydown', handleKeyDown);
  }, []);

  return ref;
}
```

```tsx
// components/molecules/ConfirmDialog.tsx — accessible dialog
import { useEffect, useRef } from 'react';
import { useFocusTrap } from '../../hooks/useFocusTrap';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open, title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel',
  onConfirm, onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useFocusTrap<HTMLDivElement>();
  const previousFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      previousFocus.current = document.activeElement as HTMLElement;
    } else {
      // Restore focus when dialog closes
      previousFocus.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape' && open) onCancel();
    }
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="presentation">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} aria-hidden="true" />
      {/* Dialog */}
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        aria-describedby="dialog-message"
        className="relative z-10 w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
      >
        <h2 id="dialog-title" className="text-lg font-semibold">{title}</h2>
        <p id="dialog-message" className="mt-2 text-gray-600">{message}</p>
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onCancel} className="px-4 py-2 rounded border">
            {cancelLabel}
          </button>
          <button onClick={onConfirm} className="px-4 py-2 rounded bg-red-600 text-white">
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
```

### Color Contrast and Screen Reader Testing

```bash
# Install axe-core for automated a11y testing
npm install --save-dev @axe-core/playwright   # Playwright
npm install --save-dev jest-axe               # Jest

# Run pa11y for CLI-based accessibility audit
npx pa11y http://localhost:3000/dashboard --standard WCAG2AA --reporter json
```

```tsx
// e2e/a11y.spec.ts — automated accessibility audit with Playwright + axe
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const routes = ['/', '/dashboard', '/users', '/login'];

for (const route of routes) {
  test(`${route} has no WCAG 2.1 AA violations`, async ({ page }) => {
    await page.goto(route);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(results.violations).toEqual([]);
  });
}
```

```tsx
// Unit-level a11y check with jest-axe
import { render } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';
import { UserForm } from '../UserForm';

expect.extend(toHaveNoViolations);

test('UserForm is accessible', async () => {
  const { container } = render(<UserForm onSubmit={async () => {}} />);
  const results = await axe(container);
  expect(results).toHaveNoViolations();
});
```

### Accessibility Checklist

| Category | Check | Tool |
|---|---|---|
| Color contrast | 4.5:1 text, 3:1 large text/UI | axe-core, Chrome DevTools |
| Keyboard access | Every interactive element reachable via Tab | Manual + Playwright |
| Focus indicators | Visible focus ring on all focusable elements | Manual |
| Headings | One h1 per page, logical h1-h6 order | axe-core |
| Forms | Every input has visible label, errors linked via aria-describedby | jest-axe |
| Images | Alt text on all informative images, aria-hidden on decorative | axe-core |
| Live regions | aria-live="polite" for async status updates | Screen reader |
| Modals | Focus trapped, Escape closes, focus restored on close | Manual + Playwright |
| Skip links | "Skip to main content" link as first focusable element | Manual |

---

