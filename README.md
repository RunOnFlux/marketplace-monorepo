# marketplace-monorepo

Monorepo for **RunOnFlux Marketplace / FluxOS-friendly** Docker images.

## Layout

- `Gaming/<project>/` → one game server image (with its own `Dockerfile`, `README.md`, and `flux-spec.json`)
- `AI/<project>/` → AI / automation tooling images (e.g. `AI/n8n`)
- `Infrastructure/<project>/` → infrastructure/support images
- `Blockchain/<project>/` → blockchain-related images

## Local builds

Build from repo root by pointing Docker at the project directory:

```bash
docker build -t <name>:local ./Gaming/<project>
```

## CI

Each project has a dedicated GitHub Actions workflow that triggers only when files in that project change.

- Pushes to GHCR under `ghcr.io/<owner>/<image>`
- Optionally pushes to Docker Hub when Docker Hub secrets are configured
