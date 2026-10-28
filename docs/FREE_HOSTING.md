# Free hosting for the Zehunger ERP

Where to run the ERP without paying, what each option costs you in other ways,
and how to deploy on the two best ones. Free plans change often: these terms
were checked on **28 October 2026**. Confirm them on each provider's own
pricing page before you sign up (links at the end).

## What the app needs

| Part | Why | Notes |
|---|---|---|
| Python web server (gunicorn) | The pages and the API | Python 3.11+; about 200–300 MB of memory with one worker |
| PostgreSQL 14+ | Every record | A few hundred MB covers years of farm records |
| Jobs every few minutes | Alerts, alert emails, clean-up | `python -m backend.jobs`; or `JOBS_IN_WEB_INTERVAL` on hosts without workers |
| HTTPS | Sign-in cookies only travel over HTTPS | Every option below provides it |
| Outgoing email (optional) | Alert emails | Several free hosts block the usual SMTP ports |

## The short answer

| | Best for | Cost | Effort |
|---|---|---|---|
| **A. Oracle Cloud Always Free VM** | Real use: always on, your own server, full backups | Free (card needed to verify identity) | Moderate: follow [DEPLOYMENT.md](../DEPLOYMENT.md) |
| **B. Render (web) + Neon (database)** | Pilots and demos; quickest to set up | Free (no card for either) | Low: connect GitHub, paste settings |
| C. Google Cloud e2-micro | Fallback if Oracle has no capacity | Free (card needed) | Moderate; only 1 GB of memory, US regions only |

Use **A** if farmers will rely on it every day. Use **B** to show the system to
partners or run a pilot this week. Move from B to A (or to a paid plan) before
real business depends on it: Render itself says its free instances are not
meant for production.

## Every platform considered

| Platform | Free terms (Oct 2026) | Verdict for this app |
|---|---|---|
| **Oracle Cloud Always Free** | Arm (Ampere A1) VMs up to 2 OCPU / 12 GB in total (halved in mid-2026), 200 GB disk, always on; home region can be **Johannesburg** | **Best free option.** Runs everything, including the jobs worker and nightly backups. Arm capacity is sometimes unavailable; idle free VMs can be reclaimed |
| **Render** | Web service with 512 MB, sleeps after 15 min idle (wakes in ~1 min), 750 h a month; no background workers or cron; SMTP ports 25/465/587 blocked; free Postgres **deleted after 30 days** | **Good for the web part only.** Pair with Neon; keep it awake with a free pinger; send email on port 2525 |
| **Neon** | Postgres, 0.5–1 GB per project, 100 compute-hours a month, sleeps after 5 min idle, 6 h restore history | **Good free database.** Enough for a pilot; take your own backups |
| **Supabase** | Postgres, 500 MB, pauses after 7 days without activity | Alternative to Neon; use its *session pooler* connection string from Render |
| **Google Cloud** | One e2-micro (2 shared vCPU, 1 GB) in us-west1/us-central1/us-east1, 30 GB disk, 1 GB egress a month | Works with swap and one worker; tight, far from Kenya, egress limit |
| **Fly.io** | No free allowance for new accounts since October 2024 (short trial only) | Not free |
| **Koyeb** | One small free web service; free Postgres a few hours a month; card and a default paid plan for new sign-ups | Not practical for this app |
| **Railway** | $5 trial for 30 days, then $1 of credit a month | Not enough to stay up |
| **PythonAnywhere** | One small web app, outgoing internet allow-listed, no Postgres, no scheduled tasks | Not suitable |
| **Vercel, Netlify, Cloudflare Pages** | Static sites and short serverless functions | Not suitable: the app is a long-running Flask server with a database pool |

## Option A: Oracle Cloud Always Free VM

The repository's [DEPLOYMENT.md](../DEPLOYMENT.md) already describes this setup
(Ubuntu, nginx, gunicorn, PostgreSQL, jobs worker, nightly backups). On
Oracle:

1. **Sign up** at oracle.com/cloud/free. Choose **South Africa Central
   (Johannesburg)** as the home region: Always Free resources can only be
   created there, and it is the closest region to Kenya. A card is needed to
   verify identity; Always Free resources are not charged.
2. **Create the VM**: *Compute → Instances → Create*. Image **Canonical Ubuntu
   24.04** (aarch64), shape **VM.Standard.A1.Flex** with **1 OCPU and 6 GB**
   (half the free allowance, leaving room for a second VM). Add your SSH key.
   If you get "Out of capacity", retry later or try another availability
   domain.
3. **Open the web ports**: in the instance's subnet *Security List*, add
   ingress rules for TCP 80 and 443 from 0.0.0.0/0. Oracle's Ubuntu images
   also block ports in the VM's own firewall:
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
4. **A name for HTTPS**: point your own domain's A record at the VM's public
   IP, or get a free subdomain from duckdns.org (e.g. `zehunger.duckdns.org`).
5. **Follow [DEPLOYMENT.md](../DEPLOYMENT.md) from section 1.** Everything in
   `deploy/` works unchanged on Arm. Leave `JOBS_IN_WEB_INTERVAL=0`; the
   `zehunger-jobs` service runs the jobs.
6. **Copy backups off the VM** (DEPLOYMENT.md section 10), for example a
   weekly copy to your PC with `scp`, or to Oracle Object Storage (20 GB free).
7. **Stay within Always Free**: keep the account on the free tier, and check
   the *Billing → Cost analysis* page after the first week shows 0.

## Option B: Render + Neon (no card)

```
browser ─HTTPS─> Render free web service (gunicorn + jobs thread) ─SSL─> Neon Postgres
cron-job.org ── every 10 min ──> /healthz   (keeps the web service awake)
```

1. **Database (Neon)**: sign up at neon.com, create a project in **AWS Europe
   Central (Frankfurt)**, Postgres 16. Copy the connection string **without
   `-pooler`** in the host name; it must end in `?sslmode=require`.
2. **Web (Render)**: sign up at render.com with GitHub, then *New → Blueprint*
   and pick the `zihanga-solutions-system` repository. Render reads
   [`render.yaml`](../render.yaml) and asks for the values marked `sync:
   false`:
   - `DATABASE_URL`: the Neon string from step 1.
   - `PUBLIC_BASE_URL`: `https://zehunger-erp.onrender.com` (the name Render
     shows; change it after the first deploy if it differs).
   - Email (optional): a free brevo.com account allows 300 emails a day; use
     its SMTP login and key for `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD`,
     your sender for `EMAIL_FROM`. Leave them empty to keep alerts in the app
     only.
   `SECRET_KEY` is generated by Render; never put it in the repository.
3. **First deploy** takes a few minutes; the start command creates every table
   (`python -m backend.init_db`) before gunicorn starts. Open
   `https://<your-service>.onrender.com/readyz`: it should say ready.
4. **First administrator**: free Render services have no shell, so run this
   once from your PC with the Neon string:
   ```bash
   pip install -r backend/requirements.txt
   DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require" python -m backend.create_super_admin
   ```
   (PowerShell: `$env:DATABASE_URL="..."; python -m backend.create_super_admin`.)
   Then sign in, open *Setup* to add the farm, sites, facilities and stores,
   and create the team's accounts in the admin portal.
5. **Keep it awake**: at cron-job.org create a job that opens
   `https://<your-service>.onrender.com/healthz` every 10 minutes. Without it
   the service sleeps after 15 idle minutes, the next visitor waits about a
   minute, and alerts stop while it sleeps. One always-on service uses about
   744 of the 750 free hours a month, so run only this one service.
   `/healthz` does not touch the database, so Neon can still sleep between
   uses and stay within its 100 compute-hours.
6. **Backups**: Neon only keeps 6 hours of history on the free plan. Take a
   weekly copy from your PC with PostgreSQL's `pg_dump`:
   ```bash
   pg_dump --format=custom --no-owner "postgresql://...neon.tech/neondb?sslmode=require" -f zehunger-$(date +%F).dump
   ```
7. **Readiness**: run `python -m backend.preflight` from your PC with the same
   settings. Expect warnings for email (if unset) and about the jobs worker
   until the first jobs run (15 minutes after start).

### Limits to tell users about (option B)

- After a deploy or restart the first page can take up to a minute.
- Uploaded files are not kept, but this app stores everything in the database.
- Neon: about 0.5–1 GB of data; the dashboard shows usage. Move to a paid plan
  or to option A well before it fills.
- Render's free terms say free instances are not for production; Render may
  suspend free services that break its fair-use rules.

## Moving off free hosting later

The app runs anywhere PostgreSQL and Python run. Restore a `pg_dump` into the
new database (DEPLOYMENT.md section 10), point `DATABASE_URL` at it, deploy the
same code. A small paid VPS (about US$5–7 a month) or Render's starter web
service (US$7) plus a paid database removes the sleep and the size limits.

## Sources (checked 28 October 2026)

- Oracle: [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm); [InfoQ on the 2026 Ampere A1 cut](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/)
- Render: [free plan limits summary](https://justinmckelvey.com/blog/is-render-free); [free Postgres limits](https://hyperobserve.com/limits/render/free-postgres/); [Render free review](https://toolfreebie.com/render-hosting-review/); official terms at render.com/docs/free
- Neon: [Free plan limits and quotas](https://neon.com/faqs/free-plan-limits-and-quotas); [Neon vs Supabase free plans](https://neon.com/guides/neon-vs-supabase-free-plan)
- Supabase: [pricing guide 2026](https://www.jetadmin.io/blog/supabase-pricing-2026-guide-to-plans-limits-and-real-world-costs/)
- Fly.io: [free tier history](https://www.saaspricepulse.com/blog/flyio-pricing-history)
- Koyeb: [free tier 2026](https://agentdeals.dev/vendor/koyeb)
- Railway: [free trial docs](https://docs.railway.com/pricing/free-trial)
- PythonAnywhere: [plans and pricing](https://www.pythonanywhere.com/pricing/)
- Google Cloud: free tier summary (third-party; confirm at cloud.google.com/free)
- Brevo: [free plan review](https://dreamlit.ai/blog/brevo-review)
