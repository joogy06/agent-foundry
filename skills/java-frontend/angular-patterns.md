# Angular Enterprise Patterns (17+)

Reference file for the `java-frontend` skill. Covers standalone components, services, routing, interceptors, and change detection patterns for Angular 17+.

## 1. Angular Enterprise Patterns (17+)

### Standalone Components (Default Since Angular 17)

```typescript
// app.component.ts — root standalone component
import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { HeaderComponent } from './shared/components/header/header.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, HeaderComponent],
  template: `
    <app-header />
    <main class="container mx-auto px-4 py-6">
      <router-outlet />
    </main>
  `,
})
export class AppComponent {}
```

```typescript
// user-list.component.ts — standalone component with signals
import { Component, computed, inject, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { UserService } from '../../core/services/user.service';
import { User } from '../../core/models/user.model';

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (loading()) {
      <div class="skeleton-loader" aria-busy="true">Loading users...</div>
    } @else if (error()) {
      <div role="alert" class="error-banner">
        <p>{{ error() }}</p>
        <button (click)="loadUsers()">Retry</button>
      </div>
    } @else {
      <div class="mb-4">
        <input
          type="search"
          [value]="searchTerm()"
          (input)="searchTerm.set($any($event.target).value)"
          placeholder="Search users..."
          aria-label="Search users"
        />
        <p class="text-sm text-gray-500">{{ filteredUsers().length }} results</p>
      </div>
      <ul role="list">
        @for (user of filteredUsers(); track user.id) {
          <li class="user-card">{{ user.name }} — {{ user.email }}</li>
        } @empty {
          <li>No users found.</li>
        }
      </ul>
    }
  `,
})
export class UserListComponent implements OnInit {
  private userService = inject(UserService);

  users = signal<User[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);
  searchTerm = signal('');

  filteredUsers = computed(() => {
    const term = this.searchTerm().toLowerCase();
    return this.users().filter(
      (u) => u.name.toLowerCase().includes(term) || u.email.toLowerCase().includes(term)
    );
  });

  ngOnInit(): void {
    this.loadUsers();
  }

  loadUsers(): void {
    this.loading.set(true);
    this.error.set(null);
    this.userService.getAll().subscribe({
      next: (users) => {
        this.users.set(users);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err.message || 'Failed to load users');
        this.loading.set(false);
      },
    });
  }
}
```

### Services with inject() and Typed HttpClient

```typescript
// core/services/user.service.ts
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { User, CreateUserDto, PaginatedResponse } from '../models/user.model';

@Injectable({ providedIn: 'root' })
export class UserService {
  private http = inject(HttpClient);
  private baseUrl = `${environment.apiUrl}/api/v1/users`;

  getAll(page = 0, size = 20): Observable<PaginatedResponse<User>> {
    const params = new HttpParams().set('page', page).set('size', size);
    return this.http.get<PaginatedResponse<User>>(this.baseUrl, { params });
  }

  getById(id: string): Observable<User> {
    return this.http.get<User>(`${this.baseUrl}/${id}`);
  }

  create(dto: CreateUserDto): Observable<User> {
    return this.http.post<User>(this.baseUrl, dto);
  }

  update(id: string, dto: Partial<CreateUserDto>): Observable<User> {
    return this.http.put<User>(`${this.baseUrl}/${id}`, dto);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
```

### Routing — Lazy Loading, Guards, Resolvers

```typescript
// app.routes.ts
import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { roleGuard } from './core/guards/role.guard';
import { userResolver } from './features/users/resolvers/user.resolver';

export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  {
    path: 'dashboard',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
  },
  {
    path: 'users',
    canActivate: [authGuard, roleGuard],
    data: { roles: ['ADMIN', 'MANAGER'] },
    loadChildren: () =>
      import('./features/users/users.routes').then((m) => m.USER_ROUTES),
  },
  {
    path: 'users/:id',
    canActivate: [authGuard],
    resolve: { user: userResolver },
    loadComponent: () =>
      import('./features/users/user-detail/user-detail.component').then(
        (m) => m.UserDetailComponent
      ),
  },
  { path: 'login', loadComponent: () => import('./features/auth/login.component').then((m) => m.LoginComponent) },
  { path: '**', loadComponent: () => import('./shared/components/not-found.component').then((m) => m.NotFoundComponent) },
];
```

```typescript
// core/guards/auth.guard.ts — functional guard (Angular 17+)
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (auth.isAuthenticated()) {
    return true;
  }
  return router.createUrlTree(['/login'], {
    queryParams: { returnUrl: location.pathname },
  });
};
```

```typescript
// core/guards/role.guard.ts — role-based functional guard
import { inject } from '@angular/core';
import { CanActivateFn, ActivatedRouteSnapshot, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const roleGuard: CanActivateFn = (route: ActivatedRouteSnapshot) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const requiredRoles: string[] = route.data['roles'] ?? [];
  if (requiredRoles.length === 0 || requiredRoles.some((r) => auth.hasRole(r))) {
    return true;
  }
  return router.createUrlTree(['/dashboard']);
};
```

```typescript
// features/users/resolvers/user.resolver.ts
import { inject } from '@angular/core';
import { ResolveFn } from '@angular/router';
import { UserService } from '../../../core/services/user.service';
import { User } from '../../../core/models/user.model';

export const userResolver: ResolveFn<User> = (route) => {
  return inject(UserService).getById(route.paramMap.get('id')!);
};
```

### Interceptors — Auth Token and Error Handling

```typescript
// core/interceptors/auth.interceptor.ts — functional interceptor (Angular 17+)
import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { Router } from '@angular/router';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const token = auth.getAccessToken();

  const authReq = token
    ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
    : req;

  return next(authReq).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status === 401 && !req.url.includes('/auth/')) {
        return auth.refreshToken().pipe(
          switchMap((newToken) => {
            const retryReq = req.clone({
              setHeaders: { Authorization: `Bearer ${newToken}` },
            });
            return next(retryReq);
          }),
          catchError(() => {
            auth.logout();
            router.navigate(['/login']);
            return throwError(() => error);
          })
        );
      }
      return throwError(() => error);
    })
  );
};
```

```typescript
// core/interceptors/error.interceptor.ts — global error handler
import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { NotificationService } from '../services/notification.service';

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const notify = inject(NotificationService);
  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      const message =
        error.error?.message || error.message || 'An unexpected error occurred';
      if (error.status >= 500) {
        notify.error('Server error. Please try again later.');
      } else if (error.status === 403) {
        notify.warn('You do not have permission to perform this action.');
      } else if (error.status === 0) {
        notify.error('Network error. Check your connection.');
      }
      return throwError(() => error);
    })
  );
};
```

Register interceptors in `app.config.ts`:

```typescript
import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { routes } from './app.routes';
import { authInterceptor } from './core/interceptors/auth.interceptor';
import { errorInterceptor } from './core/interceptors/error.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor, errorInterceptor])),
  ],
};
```

### Change Detection — OnPush and Signals

```typescript
// Prefer OnPush + signals for optimal performance
@Component({
  selector: 'app-metric-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="metric-card">
      <h3>{{ label() }}</h3>
      <p class="value">{{ formattedValue() }}</p>
      <span [class]="trendClass()">{{ trend() }}%</span>
    </div>
  `,
})
export class MetricCardComponent {
  label = input.required<string>();
  value = input.required<number>();
  trend = input<number>(0);
  format = input<'currency' | 'number' | 'percent'>('number');

  formattedValue = computed(() => {
    switch (this.format()) {
      case 'currency': return `$${this.value().toLocaleString()}`;
      case 'percent': return `${this.value()}%`;
      default: return this.value().toLocaleString();
    }
  });

  trendClass = computed(() =>
    this.trend() >= 0 ? 'trend-up' : 'trend-down'
  );
}
```

---

