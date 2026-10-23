# CareLoop UI

React, TypeScript, Vite and Tailwind UI connected to the replacement CareLoop API.
The established navy/blue visual system is retained.

## Run

From the repository root, `docker compose up --build -d` serves the application at
<http://localhost:5173>. See the [root README](../README.md) for database setup.

For development, start the API using the root README, then from `ui/`:

```sh
npm ci
npm run dev
```

Vite proxies `/api` unchanged to `http://localhost:8000`. Set
`CARELOOP_API_PROXY` to use a different backend. Production Nginx proxies the same
prefix to the Compose API service and serves client-side routes.

## Workspaces

| Route | Workflow |
|---|---|
| `/` | Patient entry/CSV, fact revisions, target proposals and explicit approval |
| `/plan` | Multi-item meal search, saved alternatives, approval and substitutions |
| `/adherence` | Item/whole-meal logging, corrections, completeness and target comparisons |
| `/foods` | Food search, reviewed portions, suitability and nutrient corrections |
| `/knowledge-review` | Source acquisition, structured drafts, review and publication |

Demo roles and actor labels are not authentication. Approval is explicit; no
clinical records or recommendations are automatically seeded. Hosted extraction
and cited chat remain pending. `/chat` explains that limitation.

## Code structure

`src/App.tsx` owns routing, navigation and the demo session. The five screens live
in `src/screens/`, with reusable controls in `src/components/`. `src/api.ts` is the
single typed API client; `src/state.ts` provides shared session and request state.
Tests live beside the application and screens. Retired screens, API contracts and
demo providers have been removed. Current workflow contracts live in `../docs/`.

## Verify

```sh
npm run build
npm run lint
npm run test -- --reporter=dot
```

Component checks cover API contracts, role switching, multi-item requests and
item-specific logging. Live browser verification uses explicitly synthetic
software-test records in a temporary database; it is not clinical validation.
