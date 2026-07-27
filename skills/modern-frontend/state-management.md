# State Management

Reference file for the `modern-frontend` skill. Covers NgRx (Angular), Redux Toolkit (React), and guidance on when to use global vs local state.

## 3. State Management

### NgRx (Angular) — Store, Effects, Selectors

```typescript
// store/users/user.state.ts
import { createFeature, createReducer, createSelector, on } from '@ngrx/store';
import { EntityState, EntityAdapter, createEntityAdapter } from '@ngrx/entity';
import { User } from '../../core/models/user.model';
import { UserActions } from './user.actions';

export interface UserState extends EntityState<User> {
  loading: boolean;
  error: string | null;
  selectedUserId: string | null;
}

export const userAdapter: EntityAdapter<User> = createEntityAdapter<User>();

const initialState: UserState = userAdapter.getInitialState({
  loading: false,
  error: null,
  selectedUserId: null,
});

export const userFeature = createFeature({
  name: 'users',
  reducer: createReducer(
    initialState,
    on(UserActions.loadUsers, (state) => ({ ...state, loading: true, error: null })),
    on(UserActions.loadUsersSuccess, (state, { users }) =>
      userAdapter.setAll(users, { ...state, loading: false })
    ),
    on(UserActions.loadUsersFailure, (state, { error }) => ({
      ...state, loading: false, error,
    })),
    on(UserActions.selectUser, (state, { userId }) => ({
      ...state, selectedUserId: userId,
    })),
    on(UserActions.deleteUserSuccess, (state, { userId }) =>
      userAdapter.removeOne(userId, state)
    ),
  ),
});

// Memoized selectors
const { selectAll, selectEntities } = userAdapter.getSelectors(userFeature.selectUsersState);
export const selectAllUsers = selectAll;
export const selectUserEntities = selectEntities;
export const selectSelectedUser = createSelector(
  selectEntities,
  userFeature.selectSelectedUserId,
  (entities, id) => (id ? entities[id] ?? null : null)
);
export const selectUsersLoading = userFeature.selectLoading;
export const selectUsersError = userFeature.selectError;
```

```typescript
// store/users/user.actions.ts
import { createActionGroup, emptyProps, props } from '@ngrx/store';
import { User } from '../../core/models/user.model';

export const UserActions = createActionGroup({
  source: 'Users',
  events: {
    'Load Users': emptyProps(),
    'Load Users Success': props<{ users: User[] }>(),
    'Load Users Failure': props<{ error: string }>(),
    'Select User': props<{ userId: string }>(),
    'Delete User': props<{ userId: string }>(),
    'Delete User Success': props<{ userId: string }>(),
    'Delete User Failure': props<{ error: string }>(),
  },
});
```

```typescript
// store/users/user.effects.ts
import { inject, Injectable } from '@angular/core';
import { Actions, createEffect, ofType } from '@ngrx/effects';
import { catchError, map, switchMap, of } from 'rxjs';
import { UserService } from '../../core/services/user.service';
import { UserActions } from './user.actions';

@Injectable()
export class UserEffects {
  private actions$ = inject(Actions);
  private userService = inject(UserService);

  loadUsers$ = createEffect(() =>
    this.actions$.pipe(
      ofType(UserActions.loadUsers),
      switchMap(() =>
        this.userService.getAll().pipe(
          map((response) => UserActions.loadUsersSuccess({ users: response.content })),
          catchError((err) => of(UserActions.loadUsersFailure({ error: err.message })))
        )
      )
    )
  );

  deleteUser$ = createEffect(() =>
    this.actions$.pipe(
      ofType(UserActions.deleteUser),
      switchMap(({ userId }) =>
        this.userService.delete(userId).pipe(
          map(() => UserActions.deleteUserSuccess({ userId })),
          catchError((err) => of(UserActions.deleteUserFailure({ error: err.message })))
        )
      )
    )
  );
}
```

### Redux Toolkit (React)

```typescript
// store/usersSlice.ts
import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import { userApi, User } from '../api/userApi';

interface UsersState {
  entities: Record<string, User>;
  ids: string[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
}

const initialState: UsersState = {
  entities: {},
  ids: [],
  loading: false,
  error: null,
  selectedId: null,
};

export const fetchUsers = createAsyncThunk('users/fetchAll', async (_, { rejectWithValue }) => {
  try {
    return await userApi.getAll();
  } catch (err: any) {
    return rejectWithValue(err.message ?? 'Failed to fetch users');
  }
});

export const deleteUser = createAsyncThunk('users/delete', async (id: string, { rejectWithValue }) => {
  try {
    await userApi.delete(id);
    return id;
  } catch (err: any) {
    return rejectWithValue(err.message ?? 'Failed to delete user');
  }
});

const usersSlice = createSlice({
  name: 'users',
  initialState,
  reducers: {
    selectUser: (state, action: PayloadAction<string | null>) => {
      state.selectedId = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchUsers.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchUsers.fulfilled, (state, action) => {
        state.loading = false;
        state.entities = {};
        state.ids = [];
        action.payload.forEach((user) => {
          state.entities[user.id] = user;
          state.ids.push(user.id);
        });
      })
      .addCase(fetchUsers.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload as string;
      })
      .addCase(deleteUser.fulfilled, (state, action) => {
        const id = action.payload;
        delete state.entities[id];
        state.ids = state.ids.filter((i) => i !== id);
      });
  },
});

// Selectors
export const selectAllUsers = (state: { users: UsersState }) =>
  state.users.ids.map((id) => state.users.entities[id]!);
export const selectUsersLoading = (state: { users: UsersState }) => state.users.loading;
export const selectUsersError = (state: { users: UsersState }) => state.users.error;
export const selectSelectedUser = (state: { users: UsersState }) =>
  state.users.selectedId ? state.users.entities[state.users.selectedId] ?? null : null;

export const { selectUser } = usersSlice.actions;
export default usersSlice.reducer;
```

### When to Use Global vs Local State

| Data Type | Where | Why |
|---|---|---|
| Auth / user session | Global (NgRx / Redux / Context) | Needed everywhere, persists across routes |
| Server cache (API data) | TanStack Query / RTK Query / HttpClient | Handles caching, refetching, staleness |
| Form input values | Local (component state / reactive forms) | Only needed by the form, discarded on unmount |
| UI state (modals, tooltips) | Local (signal / useState) | No other component needs it |
| Theme / locale | Global (Context / service) | Needed by many components, rarely changes |
| Multi-step wizard state | Scoped (parent component or context) | Shared by wizard steps, discarded on completion |

Rule of thumb: if only one component reads and writes it, keep it local. If it crosses route boundaries, lift to global.

---

