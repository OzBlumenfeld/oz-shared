# React Frontend Skill

When this skill is invoked, write or review React frontend code following the guidelines below.
Apply all rules by default. If the user provides an argument (e.g. `/react-frontend review`), focus on that mode.

---

## Language & Tooling

- React 19+ with TypeScript in strict mode (`"strict": true` in tsconfig).
- Vite for bundling. Never create-react-app.
- `pnpm` for package management unless the project already uses another.
- ESLint + `eslint-plugin-react-hooks` enforced in CI. Prettier for formatting.
- No class components — functional components only, everywhere.

---

## Project Layout

```
src/
  components/        # shared, reusable UI primitives (Button, Modal, …)
  features/          # self-contained feature slices (each owns its components, hooks, types)
    users/
      UserList.tsx
      UserCard.tsx
      useUsers.ts    # data-fetching hook for this feature
      types.ts
  hooks/             # shared custom hooks (useDebounce, useLocalStorage, …)
  lib/               # third-party wrappers and config (queryClient, axiosInstance, …)
  pages/             # route-level components — thin, just compose features
  types/             # global shared types
  App.tsx
  main.tsx
```

**Rule:** Features are the primary unit of organisation. A component that is only used in one feature lives inside that feature's folder, not in `components/`. Only promote to `components/` when genuinely reused across two or more features.

---

## Components

- One component per file. File name matches the component name (`UserCard.tsx`).
- Always type props explicitly with an interface, never inline objects or `any`.
- Destructure props at the function signature.
- Keep components small: if a component is hard to read in one screen, split it.
- No logic in JSX beyond a ternary or a `.map()`. Extract to a variable or helper first.

```tsx
interface UserCardProps {
  user: User;
  onSelect: (id: string) => void;
}

export function UserCard({ user, onSelect }: UserCardProps) {
  const handleClick = () => onSelect(user.id);

  return (
    <button onClick={handleClick} className="...">
      {user.name}
    </button>
  );
}
```

- Use named exports, not default exports. Named exports are easier to refactor and grep.

---

## TypeScript

- `strict: true` always. No `@ts-ignore` without an explanatory comment and a ticket.
- No `any`. Use `unknown` when the shape is open, then narrow with a type guard.
- Type API responses with Zod schemas at the network boundary — never trust raw JSON.
- Co-locate types with the feature that owns them. Only put types in `types/` when they span multiple features.

```ts
import { z } from "zod";

export const UserSchema = z.object({
  id: z.string().uuid(),
  name: z.string().min(1),
  email: z.string().email(),
});

export type User = z.infer<typeof UserSchema>;
```

---

## State Management

Choose the simplest option that works:

| Scope | Tool |
|-------|------|
| Local UI state (open/closed, form input) | `useState` |
| Derived values from existing state | `useMemo` / computed inline |
| Shared state across a subtree | `useContext` + `useReducer` |
| Server / async state | TanStack Query (React Query) |
| Complex global client state | Zustand (last resort) |

**Rules:**
- Don't reach for a global store when `useState` + prop drilling two levels deep is fine.
- Don't store server data in local state — put it in React Query and let it cache.
- `useContext` is for stable, low-frequency values (theme, auth user). Not for state that changes on every keystroke.

---

## Data Fetching (TanStack Query)

- All server state goes through React Query. No manual `useEffect` + `fetch` patterns.
- Define query keys as constants in the feature's `queryKeys.ts`, not inline strings.
- Separate query hooks from components (`useUsers.ts`, `useCreateUser.ts`).
- Use `queryClient.invalidateQueries` after mutations — don't manually merge into cache.

```ts
// features/users/queryKeys.ts
export const userKeys = {
  all: ["users"] as const,
  detail: (id: string) => ["users", id] as const,
};

// features/users/useUsers.ts
import { useQuery } from "@tanstack/react-query";
import { userKeys } from "./queryKeys";
import { fetchUsers } from "./api";

export function useUsers() {
  return useQuery({ queryKey: userKeys.all, queryFn: fetchUsers });
}
```

---

## API Layer (`lib/` or `features/*/api.ts`)

- Centralise all HTTP calls. Components never call `fetch` directly.
- Use an axios instance (or `ky`) configured once in `lib/http.ts` with base URL, auth headers, and error interceptors.
- Validate responses with Zod before returning. Throw on parse failure so React Query surfaces it.
- Return typed domain objects, not raw `AxiosResponse`.

```ts
// lib/http.ts
import axios from "axios";

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

http.interceptors.response.use(
  (r) => r,
  (err) => Promise.reject(err),
);
```

---

## Forms

- Use React Hook Form for any form with more than one field.
- Pair with a Zod resolver (`@hookform/resolvers/zod`) — schema defines both types and validation.
- Never manage individual field state with `useState`.

```tsx
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

const schema = z.object({ email: z.string().email(), name: z.string().min(1) });
type FormValues = z.infer<typeof schema>;

export function CreateUserForm({ onSubmit }: { onSubmit: (v: FormValues) => void }) {
  const { register, handleSubmit, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <input {...register("email")} />
      {errors.email && <p>{errors.email.message}</p>}
    </form>
  );
}
```

---

## Hooks

- A custom hook is just a function that starts with `use` and may call other hooks.
- Extract logic from components into hooks when: the logic is reused, or the component is hard to read.
- One concern per hook. `useUserForm` handles form state; `useCreateUser` handles the mutation — don't merge them.
- Never call hooks conditionally or inside loops.
- `useEffect` rules:
  - Dependency array must be exhaustive (the linter enforces this — don't disable it).
  - If an effect cleans up a subscription or timer, always return the cleanup function.
  - If you find yourself writing `useEffect` to sync state from props, reconsider — often a derived value or event handler is the right tool.

---

## Performance

- Don't pre-optimise. Profile first (React DevTools Profiler), then optimise.
- `useMemo` / `useCallback`: only when (a) a child wrapped in `React.memo` re-renders because of reference instability, or (b) an expensive computation is measurably slow. Not by default.
- `React.memo`: wrap only leaf components that re-render frequently with stable props.
- Code-split at the route level with `React.lazy` + `Suspense`.
- Images: always set `width` and `height` to prevent layout shift.

---

## Routing

- Use React Router v6+. Define routes in one place (`App.tsx` or a `routes.tsx`).
- Use `<Outlet>` for nested layouts.
- Protect routes with a wrapper component, not inside individual pages.
- Read URL params with `useParams`, search params with `useSearchParams` — never parse `window.location` manually.

---

## Styling

- Use Tailwind CSS by default. Avoid mixing Tailwind with a separate CSS-in-JS library.
- Extract repeated class strings to a component or a `cva` (class-variance-authority) variant definition — don't copy-paste long `className` strings.
- No inline `style={{}}` for anything that could be a Tailwind class.
- Dark mode: use Tailwind's `dark:` variant with a class strategy, not a media query.

---

## Error Handling

- Wrap route-level components in an `ErrorBoundary` (use `react-error-boundary`).
- React Query surfaces async errors automatically — handle them in the component with `isError` / `error` from the query result.
- Never swallow errors silently. Log to your error tracker (Sentry etc.) from the `ErrorBoundary` `onError` handler.

---

## Accessibility (a11y)

- Interactive elements must be focusable and keyboard-operable. Use `<button>` for actions, `<a>` for navigation — never `<div onClick>`.
- All `<img>` must have `alt`. Empty string `alt=""` is valid for decorative images.
- Form inputs must have associated `<label>` (via `htmlFor` or wrapping).
- Use semantic HTML (`<main>`, `<nav>`, `<section>`, `<article>`) before reaching for `<div>`.

---

## Testing

- Vitest + React Testing Library. Never test implementation details (internal state, method calls).
- Test what the user sees and does: render the component, fire events, assert on the DOM.
- Mock network calls at the HTTP boundary with MSW (Mock Service Worker), not by mocking modules.
- Co-locate tests with the component (`UserCard.test.tsx` next to `UserCard.tsx`).
- Playwright for end-to-end tests on critical flows (login, checkout, etc.).

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UserCard } from "./UserCard";

it("calls onSelect with the user id when clicked", async () => {
  const onSelect = vi.fn();
  render(<UserCard user={{ id: "1", name: "Alice" }} onSelect={onSelect} />);
  await userEvent.click(screen.getByRole("button", { name: "Alice" }));
  expect(onSelect).toHaveBeenCalledWith("1");
});
```

---

## What to Avoid

- No class components.
- No `create-react-app` or `react-scripts`.
- No direct DOM manipulation (`document.querySelector`) — use refs.
- No `useEffect` for data fetching — use React Query.
- No prop drilling beyond two levels — lift state or use context.
- No `index.ts` barrel files for components — they break tree-shaking and slow down TypeScript.
- No `console.log` left in committed code.
- No inline arrow functions on deeply nested components when they cause measurable re-renders.
- Never mutate state directly (`state.items.push(x)` — always return a new value).
