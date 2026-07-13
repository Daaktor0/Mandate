.PHONY: bootstrap check lint format-check typecheck test test-scaffold

bootstrap:
	corepack enable
	corepack prepare pnpm@10.13.1 --activate
	pnpm install --frozen-lockfile
	uv sync --locked --all-groups

check:
	pnpm check

test-scaffold:
	python3 -m unittest discover -s tests -p 'test_*.py' -v

lint:
	pnpm lint

format-check:
	pnpm format:check

typecheck:
	pnpm typecheck

test:
	pnpm test
