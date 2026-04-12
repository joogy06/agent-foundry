---
name: java-frontend
description: Use when developing enterprise frontend applications — Angular (17+, standalone components, signals, RxJS, NgRx state management), React (18+, hooks, context, Redux Toolkit, React Query/TanStack Query), TypeScript patterns, component architecture, REST/GraphQL API integration, authentication flows (OAuth2/OIDC with PKCE), form handling and validation, responsive layouts (CSS Grid/Flexbox, Tailwind), testing (Jest, Cypress, Playwright), build tooling (Vite, Webpack), and accessibility (WCAG 2.1). Part of the java-* skill family.
---

# Enterprise Frontend Development — Angular & React

Companion skill to `java-backend`, `java-spring-boot`. For API design see: `saas-architecture`, `saas-developer`. For deployment see: `docker-admin`, `docker-cicd`.

<HARD-RULE>
Never store JWT tokens in localStorage — use httpOnly cookies or in-memory storage to prevent XSS token theft. localStorage is readable by any script on the page, including injected XSS payloads. A single XSS vulnerability means every stored token is exfiltrated.
</HARD-RULE>

<HARD-RULE>
Always implement loading and error states for every async operation — unhandled states cause blank screens and confused users. Every fetch, mutation, and navigation that touches the network must have explicit pending, success, and error UI paths.
</HARD-RULE>

<HARD-RULE>
Never subscribe to observables without unsubscribing (Angular) — memory leaks accumulate and crash the browser tab in long-running SPAs. Use takeUntilDestroyed(), async pipe, or DestroyRef to guarantee cleanup. In React, always return cleanup functions from useEffect.
</HARD-RULE>

<HARD-RULE>
Always use semantic HTML elements before adding ARIA attributes — div with role="button" is never better than a real button element. Native elements provide keyboard handling, focus management, and screen reader announcements for free. ARIA is a repair tool, not a replacement.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration for each topic area are in the reference files below. Read the relevant file when working on that area.

| Topic | File | Covers |
|---|---|---|
| Angular 17+ patterns | [angular-patterns.md](angular-patterns.md) | Standalone components, services with inject(), routing (lazy loading, guards, resolvers), interceptors (auth token, error handling), change detection (OnPush, signals) |
| React 18+ patterns | [react-patterns.md](react-patterns.md) | Function components with hooks, custom hooks (useApi, useDebounce, useLocalStorage), error boundaries, React Router 6 with loaders |
| State management | [state-management.md](state-management.md) | NgRx (store, effects, selectors) for Angular, Redux Toolkit for React, guidance on global vs local state |
| API, auth, and forms | [api-auth-forms.md](api-auth-forms.md) | HttpClient typed responses, Axios with TanStack Query, GraphQL/Apollo Client, OpenAPI code generation, OAuth2 PKCE flows (Angular and React), role-based UI rendering, Angular reactive forms, React Hook Form with Zod validation |
| Components and styling | [component-styling.md](component-styling.md) | Smart/container vs presentational components, compound component pattern, Storybook documentation, Tailwind CSS configuration, responsive Grid/Flexbox layouts, CSS custom properties theming |
| Testing, build, and a11y | [testing-build-a11y.md](testing-build-a11y.md) | Jest + Testing Library (React), Jasmine + Angular testing, Playwright E2E, Mock Service Worker (MSW), Vite configuration, Nx monorepo, GitHub Actions CI/CD, environment variables, WCAG 2.1 (semantic HTML, keyboard navigation, color contrast, accessibility checklist) |

---

## Decision Guide

**Choosing a framework:**
- Angular — when the team is large, the app is complex, and you want opinionated structure (DI, modules, RxJS). Best for enterprise dashboards, admin portals, and data-heavy SPAs.
- React — when you need flexibility, a large ecosystem, and faster prototyping. Best for customer-facing apps, content-rich sites, and teams familiar with functional patterns.

**Choosing state management:**
- Local state first (useState/signals) — for component-scoped data
- Context/services — for shared state across a subtree
- NgRx/Redux Toolkit — only when you need time-travel debugging, complex async flows, or state shared across many unrelated components

**Choosing API integration:**
- REST with HttpClient/Axios — default for most APIs
- TanStack Query — when you need caching, pagination, optimistic updates
- GraphQL/Apollo — when the backend exposes a GraphQL schema and you benefit from query flexibility

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Fetching data in every component instead of using a state management solution | Duplicate requests, inconsistent data between components, excessive re-renders | Use TanStack Query (React) or NgRx/signals (Angular) for server state; colocate state with data needs |
| Not typing API responses in TypeScript | Runtime errors when API shape changes; no IDE autocomplete; bugs discovered in production instead of build | Define interfaces/types for all API responses; use zod or io-ts for runtime validation at API boundary |
| Prop drilling through 5+ component levels | Tight coupling, painful refactoring, and components that re-render unnecessarily | Use Context (React) or services with signals (Angular) for cross-cutting concerns; limit prop depth to 2-3 levels |
| Importing entire UI libraries for a few components | Bundle size balloons; 500KB of unused code shipped to users; slow page loads | Use tree-shakeable imports; import individual components; analyze bundle with webpack-bundle-analyzer |
| No error boundaries or error handling in UI | One failed API call crashes the entire application; white screen of death for users | Implement error boundaries (React) or error interceptors (Angular); show graceful fallback UI for each failure zone |

---

## Related Skills

| Domain | Skill |
|---|---|
| Java backend (Spring Boot, REST APIs) | `java-backend`, `java-spring-boot` |
| SaaS architecture (multi-tenancy, auth) | `saas-architecture` |
| SaaS implementation (tenant middleware) | `saas-developer` |
| Docker containers and CI/CD | `docker-admin`, `docker-cicd` |
| Python backend (Flask) | `python-flask-developer` |
| Auth and security patterns | `python-auth-security` |
| SEO and content optimization | `seo-structure-architect`, `seo-meta-optimizer` |
| WooCommerce frontend | `woocommerce-developer` |
| WordPress themes and blocks | `wordpress-developer` |
