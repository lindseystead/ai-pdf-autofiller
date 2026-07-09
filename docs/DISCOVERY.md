# Discovery without manual marketing

You do **not** need Render, screen recordings, HN posts, or PyPI accounts for people to find and try this project. Everything below runs automatically from GitHub.

## What runs automatically (zero work from you)

| Mechanism | What it does | Trigger |
|-----------|----------------|---------|
| **GitHub Codespaces** | One-click browser playground | User clicks badge in README |
| **GitHub Pages** | Landing page with install commands | Push to `main` |
| **Release assets** | `.whl` on every GitHub Release | Publish release |
| **GHCR container** | `docker pull ghcr.io/.../ai-pdf-autofiller` | Publish release |
| **GitHub search** | Topics + description surface the repo | Set once in repo settings |

## One-time repo settings (5 minutes, optional)

In GitHub → **Settings** → **General**:

1. **Description:** `Fill AcroForm PDFs from JSON — no field mapping. Codespaces playground.`
2. **Website:** your GitHub Pages URL (after first Pages deploy)
3. **Topics:** `pdf`, `forms`, `fastapi`, `python`, `automation`, `acroform`, `document-processing`, `self-hosted`, `api`

No blog posts required. Topics + description drive organic GitHub search traffic.

## Enable GitHub Pages (one click)

1. Repo → **Settings** → **Pages**
2. **Source:** GitHub Actions
3. Merge `pages.yml` workflow (already in repo) — next push to `main` deploys `docs/site/`

Your landing page will be: `https://lindseystead.github.io/ai-pdf-autofiller/`

## How people try it (no accounts except GitHub)

### Path A: Codespaces (best demo)

1. Click **Open in GitHub Codespaces** on README
2. Wait ~60 seconds for environment setup
3. Browser opens `/playground` via port forward
4. Upload PDF, paste JSON, download — done

### Path B: Docker (no build)

```bash
docker run -p 8000:8000 -e API_AUTH_ENABLED=false \
  ghcr.io/lindseystead/ai-pdf-autofiller:latest
```

Requires a release to have run the GHCR workflow once.

### Path C: pip without PyPI

```bash
curl -fsSL https://raw.githubusercontent.com/lindseystead/ai-pdf-autofiller/main/scripts/install-from-release.sh | bash
```

Installs the wheel from the latest GitHub Release.

## Re-run automation manually

If v0.4.0 shipped before these workflows existed:

1. **Actions** → **Release assets** → **Run workflow**
2. **Actions** → **Publish container image** → **Run workflow**

Or create a patch release `v0.4.1` to trigger both.

## Organic growth loops (still no manual posting)

1. **Issues as marketing** — Pin: "Which PDF forms should we support?" Contributors add alias packs and share their PRs.
2. **Recipes as SEO** — Each file in `recipes/` ranks for "automate W-9 python" style searches on GitHub.
3. **awesome-selfhosted** — Submit when repo is 4+ months old ([draft](submissions/awesome-selfhosted-PR.md)); one PR, passive traffic forever.
4. **Dependents** — Other repos importing yours show up in GitHub's dependency graph.

## What we removed from the critical path

| Old requirement | Automated replacement |
|-----------------|----------------------|
| Deploy Render | Codespaces + GHCR Docker |
| Record demo GIF | Terminal transcript in README + Codespaces live demo |
| PyPI token | GitHub Release wheel + install script |
| Show HN post | GitHub topics + Pages + Codespaces badge |
| Manual launch week | CI publishes artifacts on every release |

## Optional later (only if you want)

- [docs/SHOW_HN.md](SHOW_HN.md) — if you ever want a traffic spike
- [docs/PUBLISH.md](PUBLISH.md) — PyPI is optional, not required
- [docs/DEPLOY.md](DEPLOY.md) — Render is optional

The product spreads when the **try path is one click**. Codespaces is that path.
