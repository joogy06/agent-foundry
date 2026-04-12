# API Integration, Authentication, and Forms

Reference file for the `java-frontend` skill. Covers API integration (HttpClient, Axios/TanStack Query, GraphQL/Apollo, OpenAPI codegen), OAuth2 PKCE authentication, role-based UI rendering, Angular reactive forms, and React Hook Form with Zod.

## 4. API Integration

### Angular HttpClient with Typed Responses

```typescript
// api/api.service.ts — generic typed API helper
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, retry, timer } from 'rxjs';
import { environment } from '../../environments/environment';

export interface ApiOptions {
  params?: Record<string, string | number | boolean>;
  retries?: number;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private base = environment.apiUrl;

  get<T>(path: string, options?: ApiOptions): Observable<T> {
    let params = new HttpParams();
    if (options?.params) {
      Object.entries(options.params).forEach(
        ([key, val]) => (params = params.set(key, String(val)))
      );
    }
    return this.http
      .get<T>(`${this.base}${path}`, { params })
      .pipe(retry({ count: options?.retries ?? 1, delay: (_, retryCount) => timer(retryCount * 1000) }));
  }

  post<T>(path: string, body: unknown): Observable<T> {
    return this.http.post<T>(`${this.base}${path}`, body);
  }

  put<T>(path: string, body: unknown): Observable<T> {
    return this.http.put<T>(`${this.base}${path}`, body);
  }

  delete<T>(path: string): Observable<T> {
    return this.http.delete<T>(`${this.base}${path}`);
  }
}
```

### React — Axios with TanStack Query

```typescript
// api/apiClient.ts — configured Axios instance
import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { authService } from '../services/authService';

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true, // send httpOnly cookies
});

// Request interceptor — attach token
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = authService.getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor — handle 401 with silent refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config;
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        const newToken = await authService.refreshToken();
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return apiClient(originalRequest);
      } catch {
        authService.logout();
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);
```

```typescript
// api/userApi.ts — typed API functions consumed by TanStack Query hooks
import { apiClient } from './apiClient';

export interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  createdAt: string;
}

export interface CreateUserDto {
  name: string;
  email: string;
  role: string;
}

export interface PaginatedResponse<T> {
  content: T[];
  totalElements: number;
  totalPages: number;
  page: number;
}

export const userApi = {
  getAll: async (page = 0, size = 20): Promise<User[]> => {
    const { data } = await apiClient.get<PaginatedResponse<User>>('/api/v1/users', {
      params: { page, size },
    });
    return data.content;
  },
  getById: async (id: string): Promise<User> => {
    const { data } = await apiClient.get<User>(`/api/v1/users/${id}`);
    return data;
  },
  create: async (dto: CreateUserDto): Promise<User> => {
    const { data } = await apiClient.post<User>('/api/v1/users', dto);
    return data;
  },
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/api/v1/users/${id}`);
  },
};
```

### GraphQL — Apollo Client (React)

```typescript
// lib/apolloClient.ts
import { ApolloClient, InMemoryCache, createHttpLink, from } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { onError } from '@apollo/client/link/error';
import { authService } from '../services/authService';

const httpLink = createHttpLink({ uri: import.meta.env.VITE_GRAPHQL_URL });

const authLink = setContext((_, { headers }) => ({
  headers: {
    ...headers,
    authorization: authService.getAccessToken()
      ? `Bearer ${authService.getAccessToken()}`
      : '',
  },
}));

const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors) {
    graphQLErrors.forEach(({ message, locations, path }) =>
      console.error(`[GraphQL error]: ${message}`, { locations, path })
    );
  }
  if (networkError) {
    console.error(`[Network error]: ${networkError.message}`);
  }
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, authLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          users: { merge: false }, // always replace, never merge arrays
        },
      },
    },
  }),
  defaultOptions: {
    watchQuery: { fetchPolicy: 'cache-and-network' },
  },
});
```

### OpenAPI Code Generation

```bash
# Generate TypeScript API client from OpenAPI spec
npx openapi-typescript-codegen \
  --input http://localhost:8080/v3/api-docs \
  --output src/generated/api \
  --client axios \
  --useOptions

# Or with @hey-api/openapi-ts (newer alternative)
npx @hey-api/openapi-ts \
  -i http://localhost:8080/v3/api-docs \
  -o src/generated/api \
  -c @hey-api/client-axios
```

Add to `package.json` scripts:

```json
{
  "scripts": {
    "api:generate": "openapi-typescript-codegen --input http://localhost:8080/v3/api-docs --output src/generated/api --client axios --useOptions",
    "prebuild": "npm run api:generate"
  }
}
```

---

## 5. Authentication — OAuth2 PKCE

### Angular — angular-oauth2-oidc

```typescript
// core/auth/auth.config.ts
import { AuthConfig } from 'angular-oauth2-oidc';
import { environment } from '../../environments/environment';

export const authConfig: AuthConfig = {
  issuer: environment.oidcIssuer, // e.g. https://auth.example.com/realms/myapp
  redirectUri: window.location.origin + '/callback',
  postLogoutRedirectUri: window.location.origin,
  clientId: environment.oidcClientId,
  scope: 'openid profile email roles',
  responseType: 'code',  // Authorization Code + PKCE
  useSilentRefresh: true,
  silentRefreshRedirectUri: window.location.origin + '/silent-refresh.html',
  sessionChecksEnabled: true,
  showDebugInformation: !environment.production,
};
```

```typescript
// core/services/auth.service.ts
import { Injectable, inject, signal, computed } from '@angular/core';
import { OAuthService } from 'angular-oauth2-oidc';
import { authConfig } from '../auth/auth.config';
import { Router } from '@angular/router';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private oauthService = inject(OAuthService);
  private router = inject(Router);

  private _claims = signal<Record<string, any> | null>(null);
  isAuthenticated = computed(() => this.oauthService.hasValidAccessToken());
  userName = computed(() => this._claims()?.['preferred_username'] ?? 'Unknown');
  roles = computed<string[]>(() => this._claims()?.['realm_access']?.['roles'] ?? []);

  async init(): Promise<void> {
    this.oauthService.configure(authConfig);
    this.oauthService.setupAutomaticSilentRefresh();
    await this.oauthService.loadDiscoveryDocumentAndTryLogin();
    this._claims.set(this.oauthService.getIdentityClaims());
  }

  login(): void {
    this.oauthService.initCodeFlow();
  }

  logout(): void {
    this.oauthService.logOut();
  }

  getAccessToken(): string | null {
    return this.oauthService.getAccessToken() || null;
  }

  hasRole(role: string): boolean {
    return this.roles().includes(role);
  }

  refreshToken() {
    return this.oauthService.refreshToken();
  }
}
```

Bootstrap in `main.ts`:

```typescript
import { bootstrapApplication } from '@angular/platform-browser';
import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';
import { AuthService } from './app/core/services/auth.service';
import { inject, APP_INITIALIZER } from '@angular/core';

const extendedConfig = {
  ...appConfig,
  providers: [
    ...appConfig.providers,
    {
      provide: APP_INITIALIZER,
      useFactory: () => {
        const auth = inject(AuthService);
        return () => auth.init();
      },
      multi: true,
    },
  ],
};

bootstrapApplication(AppComponent, extendedConfig);
```

### React — react-oidc-context

```tsx
// providers/AuthProvider.tsx
import { AuthProvider as OidcProvider } from 'react-oidc-context';
import { WebStorageStateStore } from 'oidc-client-ts';

const oidcConfig = {
  authority: import.meta.env.VITE_OIDC_ISSUER,
  client_id: import.meta.env.VITE_OIDC_CLIENT_ID,
  redirect_uri: `${window.location.origin}/callback`,
  post_logout_redirect_uri: window.location.origin,
  scope: 'openid profile email roles',
  response_type: 'code',
  automaticSilentRenew: true,
  // Use sessionStorage instead of localStorage for tokens — cleared on tab close
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  return (
    <OidcProvider
      {...oidcConfig}
      onSigninCallback={() => {
        // Remove OIDC query params after login
        window.history.replaceState({}, document.title, window.location.pathname);
      }}
    >
      {children}
    </OidcProvider>
  );
}
```

```tsx
// hooks/useAuth.ts — convenience wrapper
import { useAuth as useOidcAuth } from 'react-oidc-context';
import { useMemo } from 'react';

export function useAuth() {
  const auth = useOidcAuth();

  const roles: string[] = useMemo(
    () => (auth.user?.profile as any)?.realm_access?.roles ?? [],
    [auth.user]
  );

  return {
    isAuthenticated: auth.isAuthenticated,
    isLoading: auth.isLoading,
    user: auth.user,
    userName: auth.user?.profile?.preferred_username ?? 'Unknown',
    roles,
    hasRole: (role: string) => roles.includes(role),
    login: () => auth.signinRedirect(),
    logout: () => auth.signoutRedirect(),
    getAccessToken: () => auth.user?.access_token ?? null,
  };
}
```

### Role-Based UI Rendering

```tsx
// components/RoleGate.tsx — React
interface RoleGateProps {
  children: React.ReactNode;
  requiredRoles: string[];
  fallback?: React.ReactNode;
}

export function RoleGate({ children, requiredRoles, fallback = null }: RoleGateProps) {
  const { hasRole } = useAuth();
  const authorized = requiredRoles.some((role) => hasRole(role));
  return authorized ? <>{children}</> : <>{fallback}</>;
}

// Usage:
// <RoleGate requiredRoles={['ADMIN']}>
//   <button onClick={handleDelete}>Delete User</button>
// </RoleGate>
```

---

## 6. Form Handling

### Angular Reactive Forms

```typescript
// features/users/user-form/user-form.component.ts
import { Component, inject, output } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  ReactiveFormsModule, FormBuilder, FormGroup, FormArray,
  Validators, AbstractControl, ValidationErrors,
} from '@angular/forms';
import { CreateUserDto } from '../../../core/models/user.model';

@Component({
  selector: 'app-user-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  template: `
    <form [formGroup]="form" (ngSubmit)="onSubmit()" novalidate>
      <div class="form-field">
        <label for="name">Full Name</label>
        <input id="name" formControlName="name" type="text"
               [attr.aria-invalid]="isInvalid('name')"
               [attr.aria-describedby]="isInvalid('name') ? 'name-error' : null" />
        @if (isInvalid('name')) {
          <p id="name-error" class="error" role="alert">
            {{ getError('name') }}
          </p>
        }
      </div>

      <div class="form-field">
        <label for="email">Email</label>
        <input id="email" formControlName="email" type="email"
               [attr.aria-invalid]="isInvalid('email')" />
        @if (isInvalid('email')) {
          <p class="error" role="alert">{{ getError('email') }}</p>
        }
      </div>

      <div class="form-field">
        <label for="role">Role</label>
        <select id="role" formControlName="role">
          <option value="">Select a role</option>
          <option value="USER">User</option>
          <option value="MANAGER">Manager</option>
          <option value="ADMIN">Admin</option>
        </select>
      </div>

      <fieldset formArrayName="phoneNumbers">
        <legend>Phone Numbers</legend>
        @for (phone of phoneNumbers.controls; track $index) {
          <div class="flex gap-2" [formGroupName]="$index">
            <input formControlName="label" placeholder="Label (e.g. Work)" />
            <input formControlName="number" placeholder="+1 555 123 4567" type="tel" />
            <button type="button" (click)="removePhone($index)" aria-label="Remove phone number">
              Remove
            </button>
          </div>
        }
        <button type="button" (click)="addPhone()">+ Add Phone</button>
      </fieldset>

      <button type="submit" [disabled]="form.invalid || submitting">
        {{ submitting ? 'Saving...' : 'Save User' }}
      </button>
    </form>
  `,
})
export class UserFormComponent {
  private fb = inject(FormBuilder);
  saved = output<CreateUserDto>();
  submitting = false;

  form: FormGroup = this.fb.group({
    name: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(100)]],
    email: ['', [Validators.required, Validators.email, this.corporateEmailValidator]],
    role: ['', Validators.required],
    phoneNumbers: this.fb.array([]),
  });

  get phoneNumbers(): FormArray {
    return this.form.get('phoneNumbers') as FormArray;
  }

  addPhone(): void {
    this.phoneNumbers.push(
      this.fb.group({
        label: ['', Validators.required],
        number: ['', [Validators.required, Validators.pattern(/^\+?[\d\s-()]{7,20}$/)]],
      })
    );
  }

  removePhone(index: number): void {
    this.phoneNumbers.removeAt(index);
  }

  corporateEmailValidator(control: AbstractControl): ValidationErrors | null {
    const email: string = control.value;
    if (!email) return null;
    const allowed = ['company.com', 'corp.company.com'];
    const domain = email.split('@')[1];
    return allowed.includes(domain) ? null : { corporateEmail: true };
  }

  isInvalid(field: string): boolean {
    const ctrl = this.form.get(field);
    return !!(ctrl?.invalid && ctrl?.touched);
  }

  getError(field: string): string {
    const ctrl = this.form.get(field);
    if (ctrl?.hasError('required')) return `${field} is required`;
    if (ctrl?.hasError('email')) return 'Invalid email address';
    if (ctrl?.hasError('corporateEmail')) return 'Must use a corporate email address';
    if (ctrl?.hasError('minlength')) return `Minimum ${ctrl.errors?.['minlength'].requiredLength} characters`;
    return 'Invalid value';
  }

  onSubmit(): void {
    if (this.form.valid) {
      this.submitting = true;
      this.saved.emit(this.form.getRawValue());
    } else {
      this.form.markAllAsTouched();
    }
  }
}
```

### React Hook Form + Zod

```tsx
// features/users/UserForm.tsx
import { useForm, useFieldArray, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const phoneSchema = z.object({
  label: z.string().min(1, 'Label is required'),
  number: z.string().regex(/^\+?[\d\s\-()]{7,20}$/, 'Invalid phone number'),
});

const userSchema = z.object({
  name: z.string().min(2, 'Name must be at least 2 characters').max(100),
  email: z
    .string()
    .email('Invalid email address')
    .refine(
      (val) => ['company.com', 'corp.company.com'].includes(val.split('@')[1] ?? ''),
      { message: 'Must use a corporate email address' }
    ),
  role: z.enum(['USER', 'MANAGER', 'ADMIN'], { required_error: 'Role is required' }),
  phoneNumbers: z.array(phoneSchema).optional(),
});

type UserFormData = z.infer<typeof userSchema>;

interface UserFormProps {
  onSubmit: (data: UserFormData) => Promise<void>;
  defaultValues?: Partial<UserFormData>;
}

export function UserForm({ onSubmit, defaultValues }: UserFormProps) {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<UserFormData>({
    resolver: zodResolver(userSchema),
    defaultValues: { name: '', email: '', role: undefined, phoneNumbers: [], ...defaultValues },
  });

  const { fields, append, remove } = useFieldArray({ control, name: 'phoneNumbers' });

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate>
      <div className="form-field">
        <label htmlFor="name">Full Name</label>
        <input
          id="name"
          {...register('name')}
          aria-invalid={!!errors.name}
          aria-describedby={errors.name ? 'name-error' : undefined}
        />
        {errors.name && (
          <p id="name-error" className="error" role="alert">
            {errors.name.message}
          </p>
        )}
      </div>

      <div className="form-field">
        <label htmlFor="email">Email</label>
        <input id="email" type="email" {...register('email')} aria-invalid={!!errors.email} />
        {errors.email && <p className="error" role="alert">{errors.email.message}</p>}
      </div>

      <div className="form-field">
        <label htmlFor="role">Role</label>
        <select id="role" {...register('role')} aria-invalid={!!errors.role}>
          <option value="">Select a role</option>
          <option value="USER">User</option>
          <option value="MANAGER">Manager</option>
          <option value="ADMIN">Admin</option>
        </select>
        {errors.role && <p className="error" role="alert">{errors.role.message}</p>}
      </div>

      <fieldset>
        <legend>Phone Numbers</legend>
        {fields.map((field, index) => (
          <div key={field.id} className="flex gap-2">
            <input {...register(`phoneNumbers.${index}.label`)} placeholder="Label" />
            <input {...register(`phoneNumbers.${index}.number`)} placeholder="+1 555 123 4567" type="tel" />
            <button type="button" onClick={() => remove(index)} aria-label="Remove phone number">
              Remove
            </button>
          </div>
        ))}
        <button type="button" onClick={() => append({ label: '', number: '' })}>
          + Add Phone
        </button>
      </fieldset>

      <button type="submit" disabled={isSubmitting}>
        {isSubmitting ? 'Saving...' : 'Save User'}
      </button>
    </form>
  );
}
```

---

