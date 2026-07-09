# Launch checklist

Use this the week you go live. Check items in order.

## Before launch (D-2 to D-1)

- [ ] **Deploy playground** — Render Blueprint from `render.yaml` → copy public URL
- [ ] **Update README** — replace `YOUR-SERVICE.onrender.com` with live hostname
- [ ] **Record demo GIF** — follow [assets/README.md](assets/README.md) → save as `docs/assets/demo.gif`
- [ ] **Publish PyPI** — add `PYPI_API_TOKEN` secret → re-run [Publish to PyPI](../.github/workflows/publish-pypi.yml)
- [ ] **Verify install** — `pip install pdf-autofiller` and `curl PLAYGROUND_URL/health`
- [ ] **Pin GitHub issue** — "Which PDF forms should we add alias packs for?"

## Launch day (D0)

**Best window:** Tuesday–Thursday, 8:00–10:00 AM US Eastern

- [ ] **Show HN** — paste from [SHOW_HN.md](SHOW_HN.md) (update playground URL first)
- [ ] **r/selfhosted** — paste from [LAUNCH.md](LAUNCH.md#reddit-rselfhosted)
- [ ] **Reply to every comment** in first 4 hours (HN ranking depends on engagement)
- [ ] **Twitter/X thread** — 5 posts from [LAUNCH.md](LAUNCH.md#twitter--x-thread-5-posts) with GIF attached to post 1

## Launch week (D+1 to D+7)

- [ ] **r/Python** — SDK angle + PyPI link
- [ ] **Product Hunt** — copy from [LAUNCH.md](LAUNCH.md#product-hunt)
- [ ] **awesome-selfhosted** — submit when eligible (see [submissions/awesome-selfhosted-PR.md](submissions/awesome-selfhosted-PR.md))
- [ ] **Fix fast** — any bugs reported on HN get a same-day patch release

## After launch (ongoing)

- [ ] Add one new recipe or alias pack per week (SEO + community)
- [ ] Cross-link playground in README badge
- [ ] Thank contributors publicly when they open alias-pack PRs

## URLs to fill in before posting

| Placeholder | Your value |
|-------------|------------|
| `https://YOUR-SERVICE.onrender.com` | Render playground base URL (no trailing slash) |
| `PYPI_URL` | `https://pypi.org/project/pdf-autofiller/` (after publish) |

Search the repo for `YOUR-SERVICE.onrender.com` and replace everywhere before launch posts.
