# Deploying to Cloudflare (Containers)

The Python web app runs unchanged in a container on Cloudflare. A small Worker
(`src/worker.js`) receives every request and forwards it to the container.

```
browser ──► Worker (tadawul-ichimoku.<you>.workers.dev) ──► Container: gunicorn + Flask (port 8080)
                                                              └─► saudiexchange.sa / Yahoo Finance
```

| File | Purpose |
|---|---|
| `Dockerfile` | Container image: Python 3.12 slim, `requirements-web.txt`, gunicorn on port 8080 |
| `src/worker.js` | Worker + `IchimokuContainer` class (sleeps after 15 min idle) |
| `wrangler.jsonc` | Worker name, container settings, Durable Object binding |
| `package.json` | Pinned `wrangler` and `@cloudflare/containers` versions |

## 1. Requirements

* A Cloudflare account on the **Workers Paid** plan. Containers are not available on the free plan.
  Containers are billed by usage on top of the plan. The container sleeps after 15 minutes without
  traffic, and a sleeping container costs nothing.
* Node.js 18+ and Docker (running) on the machine that deploys.

## 2. Create an API token

Cloudflare dashboard → **My Profile → API Tokens → Create Token**:

1. Start from the **Edit Cloudflare Workers** template.
2. Add the **Account → Containers → Edit** permission if it is not already in the template.
3. Under *Account Resources* choose only your account. Under *Zone Resources* choose only the zone you will use
   for a custom domain, or none if `workers.dev` is enough.
4. Optional: set a TTL, or restrict the token to known IP addresses.

You also need your **Account ID**, shown on the right side of the Workers & Pages overview page.

Do not use the Global API Key. It grants full access to everything in the account.

## 3. Deploy

```bash
npm install
export CLOUDFLARE_API_TOKEN=...      # from step 2
export CLOUDFLARE_ACCOUNT_ID=...
npx wrangler deploy
```

Wrangler builds the image with Docker, pushes it to Cloudflare's registry, and deploys the Worker.
It prints the URL, for example `https://tadawul-ichimoku.<subdomain>.workers.dev`.
The first container rollout can take a few minutes. Check its status with:

```bash
npx wrangler containers list
npx wrangler tail          # live logs
```

### Building behind a TLS-inspecting proxy

If `pip install` fails during the image build with `CERTIFICATE_VERIFY_FAILED`, the build machine sits
behind a proxy with its own certificate authority. Build once with the CA as a build secret. The secret is
used only for that step and is not stored in the image. Then deploy, and Wrangler reuses the cached layers:

```bash
docker build --platform linux/amd64 --secret id=ca_bundle,src=/path/to/ca-bundle.crt -t warm-cache .
npx wrangler deploy
```

## 4. Custom domain (optional)

Workers & Pages → `tadawul-ichimoku` → **Settings → Domains & Routes → Add → Custom domain**, for example
`ichimoku.example.com`. The zone must be in the same Cloudflare account.

## 5. Updating

Change the code and run `npx wrangler deploy` again. Roll back with `npx wrangler rollback`.

## Notes

* **Data access from Cloudflare:** the Saudi Exchange website may block requests from data-centre IP
  addresses. If the Tadawul source fails, the app falls back to Yahoo Finance (`--source auto`, the default).
* **Public URL:** the site is public. To limit it to specific people, put it behind
  **Cloudflare Access** (Zero Trust → Access → Applications → add the Worker's hostname).
* **Cache:** a single container instance (`"main"`) serves all visitors, so the in-memory cache is shared.
  It resets when the container sleeps.
