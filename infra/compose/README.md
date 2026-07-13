# Compose

`local.yml` is the staging-shaped worker stack used locally and in container CI.
It builds two targets from the locked worker image:

- `worker`: internal FastAPI health surface on host loopback port `8081`, with
  bounded RAM, CPU, PIDs and Chromium shared memory.
- `renderer`: health-only Phase 0 process on loopback inside a networkless
  namespace. It has no published port, a read-only root filesystem, tmpfs-only
  writable paths, no Linux capabilities, `no-new-privileges`, default seccomp,
  and the specified 1 GB / 0.5 CPU limits.

Both containers run as numeric uid/gid `10001:10001`. The image contains the
locked Python environment, Playwright Chromium, WeasyPrint's Debian runtime
libraries, and version-pinned Noto/Liberation fonts. The renderer job consumer
and render payload surface are intentionally deferred to Phase 4.

Run from the repository root:

```sh
docker compose -f infra/compose/local.yml config
docker compose -f infra/compose/local.yml up --build --detach --wait
curl --fail http://127.0.0.1:8081/health
docker compose -f infra/compose/local.yml down --remove-orphans
```

Local Compose defaults to `DEMO_MODE=1` and contains no provider credentials.
Runtime secrets remain out of the image and must be injected by the deployment
environment in later phases.
