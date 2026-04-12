# Component Architecture and Styling

Reference file for the `java-frontend` skill. Covers smart/container vs presentational components, compound component pattern, Storybook documentation, Tailwind CSS configuration, responsive layouts, and CSS theming.

## 7. Component Architecture

### Smart/Container vs Presentational Components

```
src/
├── features/                      # Smart (container) components — data fetching, state, side effects
│   ├── users/
│   │   ├── UserListPage.tsx       # Fetches data, manages state, composes presentational components
│   │   ├── UserDetailPage.tsx
│   │   └── UserForm.tsx
│   └── dashboard/
│       └── DashboardPage.tsx
├── components/                    # Presentational (dumb) components — pure UI, receive props
│   ├── atoms/                     # Smallest building blocks
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Badge.tsx
│   │   └── Spinner.tsx
│   ├── molecules/                 # Composed atoms
│   │   ├── SearchInput.tsx
│   │   ├── UserCard.tsx
│   │   ├── ErrorBanner.tsx
│   │   └── ConfirmDialog.tsx
│   └── organisms/                 # Complex compositions
│       ├── DataTable.tsx
│       ├── Sidebar.tsx
│       └── Header.tsx
├── hooks/                         # Custom hooks (shared logic)
├── api/                           # API client and typed endpoints
├── store/                         # Global state (Redux/NgRx)
└── lib/                           # Utilities, constants, type helpers
```

### Compound Component Pattern (React)

```tsx
// components/organisms/DataTable.tsx
import { createContext, useContext, useState, ReactNode } from 'react';

interface DataTableContextValue<T> {
  data: T[];
  sortField: string | null;
  sortDirection: 'asc' | 'desc';
  onSort: (field: string) => void;
}

const DataTableContext = createContext<DataTableContextValue<any> | null>(null);

function useDataTableContext() {
  const ctx = useContext(DataTableContext);
  if (!ctx) throw new Error('DataTable compound components must be used within DataTable');
  return ctx;
}

interface DataTableProps<T> {
  data: T[];
  children: ReactNode;
}

export function DataTable<T>({ data, children }: DataTableProps<T>) {
  const [sortField, setSortField] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');

  const onSort = (field: string) => {
    if (sortField === field) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const sortedData = sortField
    ? [...data].sort((a, b) => {
        const va = (a as any)[sortField];
        const vb = (b as any)[sortField];
        const cmp = va < vb ? -1 : va > vb ? 1 : 0;
        return sortDirection === 'asc' ? cmp : -cmp;
      })
    : data;

  return (
    <DataTableContext.Provider value={{ data: sortedData, sortField, sortDirection, onSort }}>
      <table role="grid" className="w-full border-collapse">{children}</table>
    </DataTableContext.Provider>
  );
}

DataTable.Header = function Header({ children }: { children: ReactNode }) {
  return <thead className="bg-gray-100">{children}</thead>;
};

DataTable.Column = function Column({ field, label }: { field: string; label: string }) {
  const { sortField, sortDirection, onSort } = useDataTableContext();
  const active = sortField === field;
  return (
    <th
      scope="col"
      className="px-4 py-3 text-left cursor-pointer select-none"
      onClick={() => onSort(field)}
      aria-sort={active ? sortDirection === 'asc' ? 'ascending' : 'descending' : 'none'}
    >
      {label} {active && (sortDirection === 'asc' ? '▲' : '▼')}
    </th>
  );
};

DataTable.Body = function Body<T>({ renderRow }: { renderRow: (item: T, index: number) => ReactNode }) {
  const { data } = useDataTableContext();
  return <tbody>{data.map((item, i) => renderRow(item as T, i))}</tbody>;
};

// Usage:
// <DataTable data={users}>
//   <DataTable.Header>
//     <tr>
//       <DataTable.Column field="name" label="Name" />
//       <DataTable.Column field="email" label="Email" />
//       <DataTable.Column field="role" label="Role" />
//     </tr>
//   </DataTable.Header>
//   <DataTable.Body renderRow={(user: User) => (
//     <tr key={user.id}><td>{user.name}</td><td>{user.email}</td><td>{user.role}</td></tr>
//   )} />
// </DataTable>
```

### Storybook Component Documentation

```typescript
// components/atoms/Button.stories.tsx
import type { Meta, StoryObj } from '@storybook/react';
import { Button } from './Button';

const meta: Meta<typeof Button> = {
  title: 'Atoms/Button',
  component: Button,
  tags: ['autodocs'],
  argTypes: {
    variant: { control: 'select', options: ['primary', 'secondary', 'danger', 'ghost'] },
    size: { control: 'select', options: ['sm', 'md', 'lg'] },
    disabled: { control: 'boolean' },
    loading: { control: 'boolean' },
  },
};
export default meta;
type Story = StoryObj<typeof Button>;

export const Primary: Story = { args: { variant: 'primary', children: 'Save Changes' } };
export const Secondary: Story = { args: { variant: 'secondary', children: 'Cancel' } };
export const Danger: Story = { args: { variant: 'danger', children: 'Delete' } };
export const Loading: Story = { args: { variant: 'primary', loading: true, children: 'Saving...' } };
export const Disabled: Story = { args: { variant: 'primary', disabled: true, children: 'Disabled' } };
```

---

## 8. Styling

### Tailwind CSS Configuration

```typescript
// tailwind.config.ts
import type { Config } from 'tailwindcss';
import defaultTheme from 'tailwindcss/defaultTheme';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx,html}'],
  darkMode: 'class', // toggle with class="dark" on <html>
  theme: {
    extend: {
      colors: {
        // Design tokens — map to CSS custom properties for theming
        brand: {
          50: 'var(--color-brand-50, #eff6ff)',
          100: 'var(--color-brand-100, #dbeafe)',
          500: 'var(--color-brand-500, #3b82f6)',
          600: 'var(--color-brand-600, #2563eb)',
          700: 'var(--color-brand-700, #1d4ed8)',
          900: 'var(--color-brand-900, #1e3a8a)',
        },
        surface: {
          DEFAULT: 'var(--color-surface, #ffffff)',
          secondary: 'var(--color-surface-secondary, #f9fafb)',
          elevated: 'var(--color-surface-elevated, #ffffff)',
        },
      },
      fontFamily: {
        sans: ['Inter', ...defaultTheme.fontFamily.sans],
        mono: ['JetBrains Mono', ...defaultTheme.fontFamily.mono],
      },
      spacing: {
        '4.5': '1.125rem',
        '18': '4.5rem',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
  ],
} satisfies Config;
```

### Responsive Layout with Grid + Flexbox

```tsx
// Responsive dashboard layout
<div className="min-h-screen bg-surface-secondary">
  {/* Sidebar — hidden on mobile, fixed on desktop */}
  <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r bg-surface lg:block">
    <nav aria-label="Main navigation" className="flex flex-col gap-1 p-4">
      {/* nav items */}
    </nav>
  </aside>

  {/* Main content — offset by sidebar width on desktop */}
  <main className="lg:ml-64">
    <header className="sticky top-0 z-20 flex items-center justify-between border-b bg-surface px-4 py-3 lg:px-6">
      <button className="lg:hidden" aria-label="Open menu">☰</button>
      <h1 className="text-lg font-semibold">Dashboard</h1>
    </header>

    {/* Metric cards — responsive grid */}
    <section className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4 lg:p-6">
      <MetricCard label="Total Users" value={1234} trend={12} />
      <MetricCard label="Active Today" value={567} trend={-3} />
      <MetricCard label="Revenue" value={89400} format="currency" trend={8} />
      <MetricCard label="Conversion" value={3.2} format="percent" trend={0.5} />
    </section>

    {/* Two-column layout on desktop, stacked on mobile */}
    <section className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-3 lg:p-6">
      <div className="lg:col-span-2">
        {/* Chart / table taking 2/3 width */}
      </div>
      <div>
        {/* Sidebar content taking 1/3 width */}
      </div>
    </section>
  </main>
</div>
```

### CSS Custom Properties for Theming

```css
/* styles/themes.css */
:root {
  --color-brand-50: #eff6ff;
  --color-brand-500: #3b82f6;
  --color-brand-600: #2563eb;
  --color-brand-700: #1d4ed8;
  --color-brand-900: #1e3a8a;
  --color-surface: #ffffff;
  --color-surface-secondary: #f9fafb;
  --color-surface-elevated: #ffffff;
  --color-text-primary: #111827;
  --color-text-secondary: #6b7280;
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
}

.dark {
  --color-brand-50: #1e3a5f;
  --color-brand-500: #60a5fa;
  --color-surface: #111827;
  --color-surface-secondary: #1f2937;
  --color-surface-elevated: #1f2937;
  --color-text-primary: #f9fafb;
  --color-text-secondary: #9ca3af;
}
```

---

