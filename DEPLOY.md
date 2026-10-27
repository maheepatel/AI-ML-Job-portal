# Deploying Gradient

Gradient ships as **one Docker container** that runs the website, the API and the
4-hourly scraper together, with SQLite on a persistent disk mounted at `/data`.
On first boot with an empty disk it copies in a bundled snapshot
(`backend/seed/gradient-seed.db`), so the site is full of jobs immediately.

Any host works if it gives you: **Docker + a persistent disk + an always-on machine
(≥1 GB RAM)**. Serverless platforms (Vercel, Netlify, Cloudflare Pages) don't
qualify: no long-running scraper, no disk.

Prices below are approximate as of October 2026. Check each provider's pricing page.

---

## 0. Before you deploy: preview locally

The exact production build, served the same way the container serves it:

```bash
cd frontend && npm run build
```

```bash
cd backend && ../.venv/Scripts/python -m gradient.cli serve
```

Open http://localhost:8270. Check `/`, `/jobs`, `/for-me`, `/status`, `/closed`.

Refresh the bundled snapshot before each deploy, so the site starts with today's jobs:

```bash
cd backend && ../.venv/Scripts/python -c "import sqlite3; s=sqlite3.connect('data/gradient.db'); d=sqlite3.connect('seed/gradient-seed.db'); s.backup(d); d.execute('VACUUM'); d.close()"
```

Settings every host needs (already in `fly.toml` for Fly):

| Variable | Value | Why |
|---|---|---|
| `GRADIENT_DATABASE_URL` | `sqlite:////data/gradient.db` | DB on the persistent disk |
| `GRADIENT_EMBEDDED_WORKER` | `true` | run the 4-hourly scraper inside the app |
| `GRADIENT_TRUST_PROXY_HEADERS` | `true` | rate-limit real visitors, not the host's proxy |
| `GRADIENT_SOURCES_IN_FLIGHT` | `24` | keeps a 1 GB machine comfortable during sweeps |
| `GRADIENT_ENABLE_LINKEDIN` | `true` / `false` | turn the LinkedIn source off if you prefer |
| Build arg `VITE_CONTACT_EMAIL` | your public email | footer "Contact" link |

Disk: mount **3 GB at `/data`**.

---

## 1. Fly.io (recommended)

**Why:** Mumbai region (fast for India), deploys straight from this folder (no public repo
needed), `fly.toml` is already written. About $5–7/month (1 GB machine + 3 GB disk). Card required.

1. **Sign up** at https://fly.io/app/sign-up and add a card (Billing).
2. **Install the CLI.** It's already installed on this PC at `C:\Users\OM PRAKASH\.fly\bin\flyctl.exe`. Elsewhere:
   ```bash
   iwr https://fly.io/install.ps1 -useb | iex
   ```
   Open a **new** terminal afterwards so `fly` is on PATH (or use the full path above).
3. **Log in.** This opens a browser page; click **Continue** within ~15 minutes or the link expires:
   ```bash
   fly auth login
   ```
   Confirm with `fly auth whoami`. It should print your email.
4. **Create the app** (from the `gradient-jobs` folder). If the name is taken, pick another and also change `app =` in `fly.toml`:
   ```bash
   fly apps create gradient-jobs
   ```
5. **Create the disk** in Mumbai:
   ```bash
   fly volumes create gradient_data --region bom --size 3 --yes
   ```
6. **Deploy.** Fly builds the image on its servers, so Docker Desktop isn't needed:
   ```bash
   fly deploy --build-arg VITE_CONTACT_EMAIL=you@example.com
   ```
7. **Check it:**
   ```bash
   fly status
   ```
   ```bash
   fly logs
   ```
   Open https://gradient-jobs.fly.dev, then `/api/health` should return `{"ok":true}` and `/status` shows the last sweep.
8. **Record the release** for rollbacks: `fly releases`, then note the top version in `ROLLBACK.md`.

Custom domain (optional): `fly certs add jobs.yourdomain.com`, then add the DNS records it prints.

---

## 2. Railway (easiest dashboard)

**Why:** clicky dashboard, Docker + volumes, about $5/month on the Hobby plan (includes $5 usage).
Regions: US, EU, Singapore (no India, so a bit slower for Indian visitors).
Deploys from **GitHub** or from this folder with the CLI.

1. Sign up at https://railway.com (GitHub login), choose the Hobby plan.
2. Install the CLI and log in:
   ```bash
   npm i -g @railway/cli
   ```
   ```bash
   railway login
   ```
3. From the `gradient-jobs` folder:
   ```bash
   railway init
   ```
   ```bash
   railway up
   ```
   Railway detects the `Dockerfile` automatically.
4. In the dashboard, open the service:
   - **Volumes:** add a volume mounted at `/data`.
   - **Variables:** add the table from section 0 (`GRADIENT_*`), plus `VITE_CONTACT_EMAIL`.
   - **Settings → Networking → Generate Domain**. Railway sets `PORT`; the app listens on it automatically.
   - **Settings → Region:** Singapore is closest to India.
5. Redeploy (`railway up`) and open the generated domain.

---

## 3. Render (simple, GitHub-based)

**Why:** straightforward Docker web service with a disk. A persistent disk needs a paid instance:
Starter at about $7/month plus about $0.25/GB for the disk. Region: Singapore is closest to India.
Needs the code in a GitHub repo (it can be private).

1. Push the repo to GitHub (private is fine; `backend/data/profile.json` and the DB are gitignored).
   Note: `/for-me` needs `profile.json` in the image, so either commit it to a **private** repo
   or regenerate it on the server (`python -m gradient.cli profile <pdf>` via the Render shell).
2. Render dashboard → **New → Web Service** → connect the repo → Runtime **Docker**.
3. Instance type **Starter** (not Free; free instances have no disk and sleep).
4. **Disks:** add a disk, mount path `/data`, size 3 GB.
5. **Environment:** add the section 0 variables. Render sets `PORT`; the app follows it.
   Health check path: `/api/health`.
6. Create the service. You get `https://<name>.onrender.com`.

---

## 4. Your own VPS (cheapest paid, most control)

**Why:** a €4–6/month server (Hetzner CX22, DigitalOcean 1 GB, Vultr; DigitalOcean and
Vultr have Bangalore regions) runs the same container. HTTPS comes from the included
Caddy setup. You maintain the server (updates, SSH).

1. Create an Ubuntu 24.04 server with ≥1 GB RAM and SSH in.
2. Install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Copy the project to the server (from your PC):
   ```bash
   scp -r "D:/Vibe coing apps/gradient-jobs" root@SERVER_IP:/opt/gradient
   ```
4. Point a domain's **A record** at `SERVER_IP`, then put that domain in `deploy/Caddyfile`.
5. Start it (on the server):
   ```bash
   cd /opt/gradient && docker compose -f deploy/docker-compose.vps.yml up -d --build
   ```
   Caddy fetches the HTTPS certificate automatically.
6. Updates later: copy the changed files again, then run the same `up -d --build` command.

---

## 5. Oracle Cloud Always Free (free, more setup)

**Why:** a genuinely free-forever ARM server (up to 4 cores / 24 GB) with a Mumbai region. The
trade-offs are a card for identity verification (no charge), a sometimes-fiddly signup, and
free ARM capacity that can be "out of capacity" in popular regions.

**A. Account** (one time)
1. Go to https://www.oracle.com/cloud/free/ → **Start for free**.
2. **Home region: India West (Mumbai).** It can't be changed later, and free resources live only there.
3. Verify the card (a temporary hold, no charge) and finish the signup. Activation can take a few minutes.

**B. Server**
1. Console menu → **Compute → Instances → Create instance**. Name it `gradient`.
2. **Image:** Change image → **Canonical Ubuntu 24.04**.
3. **Shape:** Change shape → **Ampere → VM.Standard.A1.Flex**, **2 OCPU, 12 GB** memory (shows "Always Free-eligible").
   If it says *out of capacity*: try another availability domain, retry later, or pick
   **VM.Standard.E2.1.Micro** (also Always Free, 1 GB RAM). The setup script adds swap; deploy with `SOURCES_IN_FLIGHT=8`.
4. **Networking:** create a new VCN with a **public subnet**, and keep **Assign a public IPv4 address** on.
5. **SSH keys:** **Generate a key pair for me → Save private key**. Keep the file, e.g. in your user folder's `.ssh` directory as `gradient.key`.
6. **Create**, wait for *Running*, and copy the **Public IP address**.

**C. Open the web ports**
Instance page → click the **Subnet** → **Security Lists** → *Default Security List* → **Add Ingress Rules**:
source `0.0.0.0/0`, protocol **TCP**, destination ports **80,443** → Add.
(Ubuntu's own firewall also blocks them by default. `deploy/server-setup.sh` fixes that.)

**D. Deploy** (from the `gradient-jobs` folder, in Git Bash)
```bash
bash deploy/deploy.sh <PUBLIC_IP> ~/.ssh/gradient.key
```
This installs Docker, opens the host firewall, adds swap if needed, uploads the project, builds
the image on the server and starts Gradient behind HTTPS at **https://&lt;ip-with-dashes&gt;.sslip.io**
(a free hostname that needs no DNS). Pass your own domain as a third argument once its DNS A
record points at the IP. Re-run the same command to ship updates.

Useful on the server (`ssh -i <key> ubuntu@<ip>`):
```bash
cd /opt/gradient/deploy && sudo docker compose -f docker-compose.vps.yml logs -f api
```
```bash
cd /opt/gradient/deploy && sudo docker compose -f docker-compose.vps.yml exec api python -m gradient.cli stats
```

---

## Comparison

| | Fly.io | Railway | Render | VPS | Oracle Free |
|---|---|---|---|---|---|
| Cost / month | ~$5–7 | ~$5 | ~$8 | €4–6 | $0 |
| India region | ✅ Mumbai | ❌ (Singapore) | ❌ (Singapore) | ✅ DO/Vultr Bangalore | ✅ Mumbai |
| Needs GitHub repo | No | No (CLI) | Yes | No | No |
| Setup effort | Low (CLI) | Lowest (dashboard) | Low | Medium | High |
| You maintain the OS | No | No | No | Yes | Yes |
| Config in repo | `fly.toml` | dashboard | dashboard | `deploy/` | `deploy/` |

**Not suitable:** Vercel / Netlify / Cloudflare Pages (no background scraper or disk), Heroku
(ephemeral filesystem: the DB would vanish on restart), Hugging Face Spaces free tier (no
persistent disk), Render/Railway free tiers (sleep or no disk).

---

## After any deploy

- `/api/health` returns `{"ok":true}`; `/status` shows a sweep within 4 hours of boot.
- If the domain isn't `gradient-jobs.fly.dev`, update the `og:url` / `og:image` URLs in
  `frontend/index.html` and redeploy so link previews work.
- Record the deployed version in `ROLLBACK.md`.
- Follow-ups from `LAUNCH_REPORT.md`: error tracking (Sentry) and analytics within 2 weeks.
