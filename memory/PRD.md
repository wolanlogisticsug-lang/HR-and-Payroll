# wolan Hr HR SuperApp — Zoho-style UI Redesign

## Original Problem
> "give this app a Zoho-style UI."

User-confirmed choices (Jan 2026):
- Scope: **Entire app**
- Reference: **Zoho People**
- Theme: **Light + dark toggle**
- Functionality: **only restyle, behavior unchanged**

## Architecture
- **Backend**: Django 5.2.14 (ASGI via uvicorn on :8001 wrapped by `/app/backend/server.py`)
- **Frontend shim**: `manage.py runserver 0.0.0.0:3000 --noreload` (so the public preview URL serves Django).
- **DB**: Postgres (Neon) via `DATABASE_URL` (.env).
- **Modules**: core, onboarding, attendance, payroll, leave, assets, communications, twofa.

## Done — Session 1 (Zoho People restyle)
- `/app/static/css/zoho.css` — light + dark CSS-variable tokens, sidebar/topbar/public-auth shell, dark-mode overrides for Tailwind utility classes already present in module templates.
- `/app/onboarding/templates/onboarding/base.html` — authenticated shell with collapsible left sidebar (Dashboard, Attendance, Leave, Payroll, Onboarding, Assets & NOC, Mailers, Clock In/Out), search-trigger topbar, language/theme/notifications/user-chip + dropdown menu. Active-state via path matching.
- `/app/templates/registration/_base.html` — public auth shell (login/signup extend this).
- Restyled `login.html`, `signup.html`, `setup.html`.
- Theme toggle (`localStorage.wolan Hr_theme`) applied before paint to avoid FOUC.
- `data-testid` on every new interactive element.

## Done — Session 2 (P1 features)
- **Command palette (Cmd/Ctrl+K)**
  - Backend: `core/api_views.py::search` → `GET /api/search/?q=…`
  - Searches Employees, Leave requests, Payroll, and Pages with role-scoped visibility (staff sees only their own data).
  - Frontend: modal with arrow-key navigation, Enter to open, Esc to close. Trigger via topbar search bar or `Cmd/Ctrl+K`. Platform-specific shortcut hint.
- **Notifications dropdown**
  - Backend: `core/api_views.py::notifications` → `GET /api/notifications/`
  - HR: pending leaves, pending verifications, probation ending ≤14 days.
  - Staff: own pending leaves.
  - Frontend: bell with red dot showing count, popover with tone-coloured items and timestamps.
- **Breadcrumbs**
  - `core/context_processors.py::breadcrumbs` registered in `TEMPLATES.OPTIONS.context_processors`.
  - Computes a list `[{label, url}, …]` from `request.resolver_match` (namespace + url_name) with friendly labels.
  - Rendered in the topbar via the base template.

## Verified manually (screenshots)
- Login page – light & dark.
- Root Dashboard, Attendance, Leave, Payroll, Onboarding pages – light & dark.
- Command palette (Ctrl+K) – Employees / Leave / Payroll results with active highlight, light & dark.
- Notifications dropdown – 2 items rendered ("Leave request · Adhi MD", "Verify · sethu bibin"), light & dark.
- Breadcrumbs – "Workspace / Payroll / Tax & Statutory", "Workspace / Leave / Calendar".

## Test credentials
HR `sethulakshmi` / `test1234`. Tracked in `/app/memory/test_credentials.md`.

## Next / Backlog
- P2: Per-user theme preference stored server-side (currently per-browser localStorage).
- P2: Hover/focus motion polish on tables, badges and tab transitions.
- P2: Server-side mark-as-read for notifications.
- P3: Recent-searches history in command palette.
