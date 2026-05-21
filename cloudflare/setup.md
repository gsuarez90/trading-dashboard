# Cloudflare Setup — Step 23

## Prerequisites

Before starting you need:
1. A domain name registered anywhere (Namecheap, GoDaddy, etc.) — then point its nameservers at Cloudflare
2. A free Cloudflare account at cloudflare.com
3. Your CloudFront distribution domain names from `sam deploy` output:
   - `PublicCloudfrontUrl`  → e.g. `d1abc123.cloudfront.net`
   - `PrivateCloudfrontUrl` → e.g. `d2xyz789.cloudfront.net`

Decide on your subdomain structure, e.g.:
- Public:  `app.yourdomain.com`
- Private: `private.yourdomain.com`

---

## Part 1 — Add your domain to Cloudflare

1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com)
2. Click **Add a Site** → enter your domain → choose the **Free** plan
3. Cloudflare scans your existing DNS records — review and continue
4. Copy the two Cloudflare nameservers shown (e.g. `ava.ns.cloudflare.com`)
5. Go to your domain registrar → change nameservers to the two Cloudflare ones
6. Wait for propagation (minutes to a few hours) — Cloudflare emails you when active

---

## Part 2 — DNS Records

In Cloudflare dashboard → your domain → **DNS** → **Records**

### Public frontend

| Type  | Name          | Target                        | Proxy |
|-------|---------------|-------------------------------|-------|
| CNAME | `app`         | `d1abc123.cloudfront.net`     | ✅ Proxied (orange cloud) |

> Proxied = traffic flows through Cloudflare (enables rate limiting, DDoS, Bot Fight Mode).
> Replace `app` with whatever subdomain you chose and the real CloudFront domain.

### Private frontend

| Type  | Name          | Target                        | Proxy |
|-------|---------------|-------------------------------|-------|
| CNAME | `private`     | `d2xyz789.cloudfront.net`     | ✅ Proxied (orange cloud) |

> Must be proxied — Cloudflare Access only works when traffic flows through Cloudflare.

---

## Part 3 — Public frontend security (app.yourdomain.com)

### Rate limiting
**Security** → **WAF** → **Rate limiting rules** → **Create rule**

| Setting | Value |
|---------|-------|
| Rule name | `Throttle excessive requests` |
| Field | IP Source Address |
| When rate exceeds | 30 requests per 1 minute |
| Action | Block |
| Duration | 1 hour |
| Expression | `(http.host eq "app.yourdomain.com")` |

Click **Deploy**.

### Bot Fight Mode
**Security** → **Bots** → turn **Bot Fight Mode** ON

### DDoS protection
Already on by default on all Cloudflare plans — no configuration needed.

### SSL/TLS
**SSL/TLS** → **Overview** → set mode to **Full (strict)**

---

## Part 4 — Private frontend auth (private.yourdomain.com)

This uses **Cloudflare Access** — anyone not on the allow list sees a login wall, not your dashboard.

### Enable Zero Trust
1. In Cloudflare dashboard → **Zero Trust** (left sidebar)
2. If first time: choose a team name (e.g. `yourname`) → Free plan → done

### Create an Access Application
**Access** → **Applications** → **Add an application** → **Self-hosted**

| Setting | Value |
|---------|-------|
| Application name | `Trading Dashboard Private` |
| Session duration | 24 hours |
| Application domain | `private.yourdomain.com` |

Click **Next**.

### Create an Access Policy
| Setting | Value |
|---------|-------|
| Policy name | `Owner only` |
| Action | Allow |
| Include rule | Emails → `george.suarez.2@outlook.com` |

Click **Next** → **Add application**.

### How login works
When you visit `private.yourdomain.com`:
1. Cloudflare Access intercepts the request
2. You enter your email (`george.suarez.2@outlook.com`)
3. Cloudflare emails you a one-time PIN
4. You enter the PIN → you're in for 24 hours
5. Anyone else → blocked entirely, never reaches your app

No username/password to manage. No app to install. Just email + PIN.

---

## Part 5 — CloudFront custom domain (required for CNAME to work)

CloudFront needs to know about your custom domain or it will reject requests arriving via Cloudflare.

For each distribution, in the **AWS Console** → **CloudFront** → your distribution → **Edit**:

1. **Alternate domain names (CNAMEs)** → add your custom domain:
   - Public distribution: `app.yourdomain.com`
   - Private distribution: `private.yourdomain.com`
2. **Custom SSL certificate** → Request or import an ACM certificate for your domain
   - Go to **ACM** (us-east-1 — CloudFront requires this region) → Request public certificate
   - Add both `app.yourdomain.com` and `private.yourdomain.com` (or `*.yourdomain.com`)
   - Validate via DNS (Cloudflare DNS makes this easy — ACM gives you a CNAME to add)
   - Once issued, select it in CloudFront

> This step is what allows `app.yourdomain.com` to resolve to CloudFront without an SSL error.

---

## Verification checklist

- [ ] `app.yourdomain.com` loads the public frontend over HTTPS
- [ ] `private.yourdomain.com` shows the Cloudflare Access login page
- [ ] After PIN login, `private.yourdomain.com` loads the private frontend
- [ ] A second browser (incognito, different email) is blocked at `private.yourdomain.com`
- [ ] 31 rapid requests to `app.yourdomain.com` triggers the rate limit (returns 429)

---

## Cost

| Resource | Cost |
|----------|------|
| Cloudflare Free plan | $0 |
| Cloudflare Zero Trust (up to 50 users) | $0 |
| ACM certificate | $0 |
| Domain name | ~$10–15/year (registrar cost) |
