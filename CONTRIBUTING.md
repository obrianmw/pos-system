# Contributing to POS System

Thanks for helping. Everyone is welcome to propose changes. **Only the maintainer merges into `master`**,
so every change arrives as a pull request.

## How to propose a change

1. **Fork** the repository (or, if you were added as a collaborator, create a branch).
   Name branches after the work, e.g. `fix/receipt-vat-rounding` or `feature/loyalty-points`.
2. Set it up locally. See *Quick start* in the [README](README.md).
3. Make your change with tests:
   - backend: `cd backend && .venv/Scripts/python -m pytest` (add tests under `backend/tests/`)
   - frontend: `cd frontend && npx tsc -b && npx vite build`
4. **Open a pull request into `master`.** Fill in the template, saying what changed, why, and how you tested it.
5. The **Tests** workflow runs automatically. Both checks must pass:
   *Backend tests (Django)* and *Frontend build (React + TypeScript)*.
6. The maintainer reviews it and, when it is ready, merges it.

## Rules on `master`

- Nobody except the maintainer can push to or merge into `master`. Pushes from anyone else are refused.
- Force-pushes and deleting `master` are blocked for everyone.
- Pull requests need both test checks to pass.

## Please don't commit

- `.env` files, passwords, API keys or tokens (use `.env.example` with empty values)
- `backend/db.sqlite3`, `backend/media/`, `.run/`, `node_modules/`, `.venv/` (they are ignored already)
- Real customer, staff or sales data. Use the demo data (`manage.py seed_demo`).

## Reporting a security problem

Please don't open a public issue for security problems. Contact the maintainer privately through
GitHub (profile [@obrianmw](https://github.com/obrianmw)).
