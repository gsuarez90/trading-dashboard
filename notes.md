# AI Trading Dashboard — Dev Notes

## Defense in Depth — Security Layers

Each layer assumes the one above it can be breached. No single layer is the whole answer.

| Layer | What it protects | How |
|-------|-----------------|-----|
| User → App | Frontend access | Cloudflare Access — only your email can reach `private.yourapp.com` |
| App → AWS | AWS resources | IAM execution role — Lambda can only touch its specific DynamoDB table, S3 buckets, SSM/Secrets Manager paths |
| App → External services | Third-party accounts | Secrets Manager — credentials fetched at runtime, never in code or deployment artifacts |
| Data at rest | Stored data | KMS — DynamoDB, SSM SecureString, Secrets Manager all encrypted; unreadable without the KMS key |

**Machine-to-machine (M2M)** is the credential layer between your app and external services (Robinhood, Anthropic, Polygon). Secrets Manager is the AWS tool for this. Even if someone obtained your Lambda deployment package, there are no credentials in it — the package only contains code that knows *where* to fetch credentials, not the credentials themselves.

**Auto-rotation (when applicable):**
- Rotation is invisible to the user — the app just keeps working because it always fetches fresh credentials at runtime
- Native rotation exists for RDS, Redshift, DocumentDB — AWS provides the rotation Lambda
- For static third-party credentials (Robinhood, Alpaca, API keys) — no rotation, but Secrets Manager still gives you secure storage + IAM-gated access + CloudTrail audit trail
- User-facing password prompts are a completely separate concern (Cognito/Auth0) — Secrets Manager manages backend service credentials, not human login flows

---

## SAM → SSM/Secrets Manager Flow (Where API Keys Actually Go)

The same one-time CLI handoff pattern applies to both SSM (API keys) and Secrets Manager (Robinhood credentials). SAM creates the resource shell; you fill it with real values via CLI; real values never touch a file or git.

**Step 1 — Load API keys into SSM before first deploy**
```bash
aws ssm put-parameter --name /trading-app/anthropic-key --value "your-key" --type SecureString
aws ssm put-parameter --name /trading-app/polygon-key   --value "your-key" --type SecureString
aws ssm put-parameter --name /trading-app/finnhub-key   --value "your-key" --type SecureString
```

**Step 2 — Deploy with SAM**
```bash
sam build && sam deploy
```
SAM resolves `{{resolve:ssm-secure:/trading-app/anthropic-key}}` at deploy time and injects the value into the Lambda environment. Available in code as `os.environ['ANTHROPIC_API_KEY']`.

**Step 3 — Load Robinhood credentials into Secrets Manager after deploy**
```bash
aws secretsmanager put-secret-value \
  --secret-id /trading-app/robinhood-credentials \
  --secret-string '{"username": "real_user", "password": "real_pass"}'
```
SAM creates the secret resource on deploy (with placeholder values); this command replaces the placeholder with real credentials.

**Mental model:**
- SSM / Secrets Manager = the vault where real values live
- `template.yaml` = wiring diagram — references the vault, never holds values
- CLI commands = one-time handoff from your knowledge into the vault
- `.env.local` = local dev only, gitignored, never deployed

---

## Encryption & Secrets Architecture

### Encryption in flight (TLS/SSL)
- All AWS service endpoints use HTTPS — TLS in flight is assumed for all client-to-Lambda and Lambda-to-AWS-service communication
- Protects against MITM attacks; data is unreadable if intercepted in transit
- Not something you configure per-service — it's the default for all AWS endpoints

### Server-side encryption at rest
- The server (AWS) encrypts data after receiving it and stores it encrypted on disk
- Client communicates over HTTPS; the at-rest encryption layer is transparent to the client
- The server manages a data key, often protected by a KMS master key
- Relevant here: DynamoDB encryption at rest (default on), S3 bucket encryption (SSE-S3 or SSE-KMS)

### Client-side encryption
- Client encrypts data before sending; server only ever stores ciphertext
- Client owns and manages the key — AWS cannot read the data
- Use case: storing data in S3 where even AWS should not have access
- Not needed for this app's current scope, but good to know for future sensitive data

---

## KMS (Key Management Service)
- Fully managed key service; all encrypt/decrypt operations happen inside KMS — keys never leave
- Every KMS API call is logged in CloudTrail — full audit trail
- SSM Parameter Store SecureString and Secrets Manager both use KMS under the hood
- 4 KB limit on direct KMS encrypt/decrypt — larger data uses envelope encryption (GenerateDataKey)

---

## Secrets Manager vs SSM Parameter Store

| | SSM Parameter Store (SecureString) | Secrets Manager |
|---|---|---|
| Cost | Free | $0.40/secret/month |
| Use for | API keys, config values | Account credentials, passwords |
| Auto-rotation | No | Yes (with Lambda) |
| Versioning | Basic | Full with staged labels |
| AWS integrations | Good | Native RDS/Redshift rotation |

**Rule for this app:**
- `ANTHROPIC_API_KEY`, `POLYGON_API_KEY`, `FINNHUB_API_KEY` → **SSM Parameter Store (SecureString)**
- `ROBINHOOD_USERNAME` / `ROBINHOOD_PASSWORD` → **Secrets Manager** (real financial account credentials)

---

## SAM + Secrets Manager Pattern

SAM defines the secret resource and IAM policy. Real values are loaded via CLI post-deploy — never in code or git.

**template.yaml resource:**
```yaml
RobinhoodCredentials:
  Type: AWS::SecretsManager::Secret
  Properties:
    Name: /trading-app/robinhood-credentials
    Description: Robinhood username and password for private Lambda
    SecretString: '{"username": "placeholder", "password": "placeholder"}'
```

**IAM policy on the Lambda:**
```yaml
Policies:
  - AWSSecretsManagerGetSecretValuePolicy:
      SecretArn: !Ref RobinhoodCredentials
```

**One-time CLI command after deploy (real values never touch git):**
```bash
aws secretsmanager put-secret-value \
  --secret-id /trading-app/robinhood-credentials \
  --secret-string '{"username": "real_user", "password": "real_pass"}'
```

**Runtime fetch in `robinhood_service.py`:**
```python
import boto3, json

client = boto3.client('secretsmanager')
secret = json.loads(
    client.get_secret_value(SecretId='/trading-app/robinhood-credentials')['SecretString']
)
username = secret['username']
password = secret['password']
```

Real values live in AWS Secrets Manager — KMS-encrypted, IAM-gated. Only the Lambda execution role and the account owner can retrieve them.

---

## Security Gaps Found in Kickoff Doc (v5) — Fixed

1. **Robinhood credentials missing from cloud secrets** — `.env.local` had them for local dev but no SSM/Secrets Manager entry existed for the deployed private Lambda. Fixed: added Secrets Manager resource to SAM template.
2. **SSM resolve syntax** — `{{resolve:ssm:...}}` pulls plaintext SSM params. For SecureString encrypted params, must use `{{resolve:ssm-secure:...}}`. Fixed on all three API key references.
3. **KMS and Secrets Manager missing from AWS Services Used** — both are in play (SSM SecureString and Secrets Manager are both KMS-backed). Fixed in resume/portfolio section.


## Who does have access to the KMS Key?
**In your AWS account, by default:**                                                                      

The AWS account root user — has full access to everything including KMS. This is you.                                                                                                                                                         
IAM principals you explicitly grant access to via the KMS keypolicy:                                                 
  - Your Lambda execution role — granted kms:Decrypt so it can readSecureString params and Secrets Manager values
  - Your IAM user (the one you use with the CLI) — granted admin access to manage the key
  - No one else unless you add them

What AWS (the company) can access:
  - This is the important one — AWS employees do not have access to your KMSkeys  or the data they protect
  - AWS manages the hardware (HSMs) but the key material is isolated to   your account
  - AWS cannot decrypt your data on your behalf without your explicit authorization
  - This is the contractual and technical guarantee behind KMS

What that means practically for your app:
  - You (root + IAM user via CLI) → full access
  - Your Lambda → decrypt only, scoped to specific resources
  - Cloudflare, Polygon, anyone external → no access at all
  - AWS employees → no access
  - Anyone who breaches S3/DynamoDB storage layer directly → gets encrypted data they can't read

The key policy in KMS is what enforces all of this — it's the definitive access list. CloudTrail logs every time any of these principals uses the key, so you'd have a full audit trail if anything unexpected happened.

---

## What Vite Is

Vite is a frontend build tool — it serves two purposes:

1. **Dev server** (`npm run dev`) — runs locally with hot reload so changes appear instantly without a manual refresh
2. **Production bundler** (`npm run build`) — takes all React components, CSS, and JS and packages them into optimized static files ready to upload to S3

It replaces older tools like Create React App or Webpack, and is significantly faster because it uses native ES modules during development instead of bundling everything upfront.

**Why it matters for this project specifically:**
- The `npm run build` output is what gets synced to S3 in the GitHub Actions deploy workflow
- `VITE_API_URL` is how the frontend knows which backend to call (public vs private deployment) — Vite bakes env vars prefixed with `VITE_` into the built bundle at build time

Stack summary: **React** = the UI framework (components, state, rendering) + **Vite** = the tooling that runs and builds it.

---

## ES Modules (ESM)

ES modules is the modern JavaScript standard for splitting code across files that can share functionality. Before ESM, there was no built-in module system — developers used CommonJS (`require()`/`module.exports`), which Node.js popularized. ESM was standardized in ES2015 and is now natively supported by all modern browsers and Node.

The syntax:
```js
// export from one file
export function add(a, b) { return a + b }

// import in another file
import { add } from './math.js'
```

**Why it matters for Vite:** During development, Vite serves source files as-is directly to the browser using native ESM — the browser itself handles the imports. This is why Vite starts nearly instantly regardless of project size, while older tools like Webpack had to bundle everything into one big file before you could load the page at all. For production, Vite still bundles (via Rollup) for optimized S3 deployment.

**Practical takeaway:** React components use ESM automatically via `import`/`export`. It's the reason Vite is fast — no upfront bundling in dev.

---

## Running PowerShell Scripts

PowerShell won't execute scripts in the current directory by name alone — you must prefix with `.\` to tell it to look locally:

```powershell
.\scripts\start.ps1   # from repo root
.\start.ps1           # if already inside scripts\
```

Without `.\`, PowerShell looks for a system command named `start` and ignores `.ps1` files in the working directory. This is a security default, not a bug.

---

## chmod +x and the Shebang Line

`chmod +x script.sh` sets the Unix executable permission bit on a file — a one-time operation. After that you can run the script directly (`./script.sh`) instead of passing it explicitly to the interpreter (`bash script.sh`).

The **shebang** (`#!/usr/bin/env bash` on line 1) is what makes direct execution work — when you run the file, the OS reads that first line and knows which interpreter to use. Without it, the OS wouldn't know what to do with the file.

The `./` prefix is still required because the shell won't search the current directory for executables by default (same reason as `.\` in PowerShell).

On Windows/Git Bash, `chmod +x` works within the Git Bash layer but the executable bit doesn't carry over to PowerShell or Windows Explorer — so `bash scripts/start.sh` is the more portable option on Windows.

---

## AWS SAM (Serverless Application Model)

SAM stands for **Serverless Application Model** — AWS's framework for defining and deploying serverless infrastructure using a simplified YAML template. You describe Lambda functions, API Gateway routes, DynamoDB tables, S3 buckets, etc. in `template.yaml`, and SAM compiles it down to CloudFormation and deploys it. It's the IaC tool for this project.

---

## Activating the Python Virtual Environment

**PowerShell:**
```powershell
backend\.venv\Scripts\Activate.ps1
```

**Git Bash:**
```bash
source backend/.venv/Scripts/activate
```

After activation, `(.venv)` appears in the prompt. The venv must be active to use packages installed in it (like `schwab-py`, `uvicorn`, etc.). The `start.ps1` / `start.sh` scripts handle this automatically.

## Finnhub VADER Sentiment Scores

Sentiment is scored using VADER (Valence Aware Dictionary and sEntiment Reasoner), a rule-based NLP model. For each ticker, Finnhub news headlines and summaries from the past 3 days are fetched and each article is scored from -1.0 to +1.0. All article scores are averaged into a single compound score.

| Score | Label |
|-------|-------|
| ≥ +0.05 | bullish |
| ≤ -0.05 | bearish |
| between | neutral |

The thresholds are intentionally tight — VADER tends to read financial headlines as weakly positive even on neutral days. `article_count` indicates data reliability: a score of +0.80 on 1 article is far less reliable than +0.20 on 12 articles.

## First SAM Deploy — Step-by-Step

All commands run from the repo root in any terminal with `aws` CLI installed and credentials configured (`aws configure` or env vars).

**Step 1 — Create SSM parameters (plain config values)**
```bash
aws ssm put-parameter --name /trading-app/portfolio-mode --value live --type String
aws ssm put-parameter --name /trading-app/trading-mode --value paper --type String
aws ssm put-parameter --name /trading-app/profit-mode --value cash_intraday --type String
aws ssm put-parameter --name /trading-app/trade-scope --value holdings_only --type String
aws ssm put-parameter --name /trading-app/daily-goal --value 100 --type String
aws ssm put-parameter --name /trading-app/daily-loss-limit --value 200 --type String
aws ssm put-parameter --name /trading-app/daily-trade-limit --value 3 --type String
aws ssm put-parameter --name /trading-app/max-position-size-pct --value 20 --type String
```

**Step 2 — Load API keys as SecureString (encrypted)**
```bash
aws ssm put-parameter --name /trading-app/anthropic-key --value "YOUR_KEY" --type SecureString
aws ssm put-parameter --name /trading-app/finnhub-key --value "YOUR_KEY" --type SecureString
aws ssm put-parameter --name /trading-app/schwab-client-id --value "YOUR_ID" --type SecureString
aws ssm put-parameter --name /trading-app/schwab-client-secret --value "YOUR_SECRET" --type SecureString
```

**Step 3 — Build and deploy the SAM stack**
```bash
sam build && sam deploy
```
This creates Lambda functions, DynamoDB, S3 buckets, CloudFront distributions, IAM roles, and Secrets Manager secrets. Outputs include the API Gateway URL and CloudFront URLs.

**Step 4 — Seed the Schwab OAuth token into Secrets Manager**
```bash
aws secretsmanager put-secret-value \
  --secret-id /trading-app/schwab-token \
  --secret-string "$(cat backend/schwab_token.json)"
```

**Step 5 — Add GitHub repository secrets** (Settings → Secrets → Actions)
- `AWS_DEPLOY_ROLE_ARN` — OIDC role ARN so CI/CD can deploy without long-lived keys
- `PUBLIC_API_URL` — API Gateway URL from `sam deploy` output
- `PRIVATE_API_URL` — same URL (same Lambda, different frontend build)
- `PUBLIC_CF_DIST_ID` — CloudFront distribution ID for `trading-dashboard-public`
- `PRIVATE_CF_DIST_ID` — CloudFront distribution ID for `trading-dashboard-private`

After Step 5, every push to `main` that touches `backend/`, `frontend/`, `template.yaml`, or `samconfig.toml` automatically deploys via GitHub Actions.

---

## Cloudflare + Custom Domain Setup (Step 23)

Full step-by-step config lives in `cloudflare/setup.md`. Key things to know:

### Non-obvious prerequisite — ACM certificate + CloudFront alternate domain

CloudFront rejects requests for your custom domain until you do two things in AWS:

1. **Request an ACM certificate in `us-east-1`** (CloudFront requires this region specifically — certificates in other regions won't appear in CloudFront's dropdown)
   - Go to ACM → Request public certificate → add both subdomains (e.g. `trading.yourdomain.com` and `private.yourdomain.com`, or `*.yourdomain.com`)
   - Validate via DNS — ACM gives you a CNAME record to add; if your DNS is in Cloudflare this takes ~2 minutes
2. **Add the custom domain to each CloudFront distribution**
   - CloudFront → your distribution → Edit → Alternate domain names → add `trading.yourdomain.com`
   - Select the ACM certificate you just issued

Without this, you get an SSL error even after DNS is pointing correctly.

### Private dashboard login flow

Cloudflare Access intercepts every request to `private.yourdomain.com`:
1. Enter your email (`your-email@example.com`)
2. Check email for 6-digit PIN
3. Enter PIN → authenticated for 24 hours

No app, no password manager, no username/password to manage. Anyone else hits a wall before your app is ever reached.

### DNS setup (Porkbun + Cloudflare)

You keep the domain registered at Porkbun — that never changes. You change the **nameservers** at Porkbun to point to Cloudflare's. Cloudflare then manages all DNS. Your existing project's records get migrated during Cloudflare's setup wizard. Two CNAME records for the trading app:

| Subdomain | Points to | Proxy |
|-----------|-----------|-------|
| `trading.yourdomain.com` | `d1abc.cloudfront.net` | ✅ Proxied |
| `private.yourdomain.com` | `d2xyz.cloudfront.net` | ✅ Proxied |

Both must be proxied (orange cloud) — Cloudflare Access only works when traffic flows through Cloudflare.

### Why Cloudflare instead of all-AWS

Porkbun is a registrar only — it can point DNS records but has no proxy layer, WAF, or auth. The all-AWS equivalent (WAF + Cognito + Lambda@Edge) runs ~$10–15/mo and requires code. Cloudflare's free tier covers everything: DDoS, rate limiting, Bot Fight Mode, and Access auth.

---

## Pre-Phase 2 Checklist (before Steps 25–37)

Complete these in order before starting Phase 2 work.

### 1. Performance Optimization Pass (do first — testable locally, no AWS needed)
Audit and fix real bottlenecks before deploying so optimized code ships from day one.
The bottlenecks in this app are network I/O and Lambda cold starts, not algorithmic complexity.

**a) Parallel API calls in `context_loader.py`**
If `load_context()` calls Schwab, Finnhub, and DynamoDB sequentially, convert to `asyncio.gather()`.
Sequential: 3 calls × ~500ms = ~1500ms. Parallel: ~500ms (longest single call). ~60% reduction.
Testable locally with uvicorn before any AWS deployment.

**b) DynamoDB query patterns**
Audit every DynamoDB call — ensure all use `query` via the GSI (`status-date-index`), never `scan`.
A scan reads every item in the table; a query is filtered at DynamoDB level.
Testable locally against the real DynamoDB table.

**c) Lambda package size** (check during `sam build`, not before)
Smaller deployment `.zip` = faster cold start. Run `sam build` and check the package size.
Audit `requirements.txt` for unused dependencies: `pip install pipdeptree && pipdeptree`

### 2. First AWS Deploy
See "First SAM Deploy — Step-by-Step" runbook above.
`sam build` (check `.zip` size here) → `sam deploy` → seed Schwab token into Secrets Manager → add GitHub secrets.

### 3. Infrastructure & Domain Setup
See the detailed runbook below: "Porkbun → Cloudflare Setup (Step-by-Step)"

High-level checklist:
- [ ] Add domain to Cloudflare, review imported DNS records, change Porkbun nameservers
- [ ] Wait for propagation (minutes to 24h) — check at whatsmydns.net
- [ ] Add two proxied CNAME records in Cloudflare (trading + private subdomains → CloudFront URLs from Step 2)
- [ ] Request ACM certificate in `us-east-1`, validate via Cloudflare DNS CNAMEs
- [ ] Attach ACM cert to both CloudFront distributions (Alternate domain names)
- [ ] Configure Cloudflare: rate limiting (30 req/min), Bot Fight Mode, Access application (email OTP)
- [ ] Add GitHub secrets for CI/CD auto-deploy (`AWS_ROLE_ARN`, `PUBLIC_CLOUDFRONT_ID`, `PRIVATE_CLOUDFRONT_ID`, `PUBLIC_S3_BUCKET`, `PRIVATE_S3_BUCKET`)

---

## Porkbun → Cloudflare Setup (Step-by-Step)

This is your first time doing this. Do it in order — each step unlocks the next.

### Phase A — Add your domain to Cloudflare

1. Go to cloudflare.com → create a free account (or log in)
2. Click **Add a site** → enter your domain (e.g. `yourdomain.com`) → click **Add site**
3. Select the **Free** plan → click **Continue**
4. Cloudflare scans your existing Porkbun DNS records and shows you a list of imported records
5. **Review every record carefully** — compare against what Porkbun currently shows under your domain's DNS settings
   - Your existing portfolio site's A record or CNAME should be there
   - MX records (email), TXT records (email verification) should all be present
   - If anything is missing, add it manually before proceeding
   - Set proxy status (orange cloud vs grey cloud) as needed — orange = Cloudflare proxies traffic, grey = DNS only
6. Click **Continue** — Cloudflare shows you two nameserver addresses (e.g. `aria.ns.cloudflare.com`, `bob.ns.cloudflare.com`)
7. **Do not close this page yet** — you need those nameserver addresses for the next step

### Phase B — Change nameservers at Porkbun

1. Log in to Porkbun → go to **Domain Management** → click your domain
2. Find the **Nameservers** section (usually labeled "Edit Nameservers" or "Custom Nameservers")
3. By default Porkbun shows its own nameservers (e.g. `curitiba.ns.porkbun.com`) — replace all of them
4. Enter Cloudflare's two nameserver addresses from Phase A
5. Save — Porkbun will warn you that this hands off DNS control, that's expected
6. Back in Cloudflare, click **Done, check nameservers**

Propagation takes anywhere from a few minutes to 24 hours. Cloudflare emails you when it detects the change. You can check progress at **whatsmydns.net** — search your domain, select NS record type, and watch for Cloudflare's nameservers to appear globally.

**Your existing portfolio site stays up during propagation** — both Porkbun and Cloudflare have the same records at this point, so requests resolve correctly either way.

### Phase C — Add trading app DNS records (do after SAM deploy — you need CloudFront URLs)

Once propagation is confirmed and you have the CloudFront domain names from your SAM deploy:

1. In Cloudflare → your domain → **DNS** → **Add record**
2. Add the first record:
   - Type: `CNAME`
   - Name: `trading` (resolves to `trading.yourdomain.com`)
   - Target: your public CloudFront URL (e.g. `d1abc123.cloudfront.net`)
   - Proxy status: **Proxied** (orange cloud — required for rate limiting)
3. Add the second record:
   - Type: `CNAME`
   - Name: `private` (resolves to `private.yourdomain.com`)
   - Target: your private CloudFront URL (e.g. `d2xyz456.cloudfront.net`)
   - Proxy status: **Proxied** (orange cloud — required for Cloudflare Access)
4. Both records save instantly — no propagation wait needed since Cloudflare already controls DNS

### Phase D — ACM certificate (do after Phase C DNS records are live)

1. Open AWS Console → switch region to **us-east-1** (required for CloudFront)
2. Go to **Certificate Manager** → **Request a certificate** → **Request a public certificate**
3. Add domain names:
   - `trading.yourdomain.com`
   - `private.yourdomain.com`
   - (optionally `*.yourdomain.com` to cover both with one cert)
4. Validation method: **DNS validation** → click **Request**
5. ACM shows you CNAME records to add for validation (one per domain)
6. In Cloudflare → DNS → add each validation CNAME record ACM gives you
   - Proxy status: **DNS only** (grey cloud) — ACM validation requires this
7. ACM validates automatically within ~2 minutes once DNS resolves. Status changes from **Pending** to **Issued**.

### Phase E — Attach cert to CloudFront

1. AWS Console → **CloudFront** → click your public distribution → **Edit**
2. Under **Alternate domain names (CNAMEs)** → add `trading.yourdomain.com`
3. Under **Custom SSL certificate** → select the ACM cert you just issued
4. Save — CloudFront deploys the change (~5 min)
5. Repeat for the private distribution: alternate domain `private.yourdomain.com`, same cert
6. Test: visit `https://trading.yourdomain.com` — should load your public frontend

### Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Site down after nameserver change | DNS record missing in Cloudflare import | Add the missing record in Cloudflare DNS |
| SSL error after custom domain | ACM cert not attached to CloudFront | Complete Phase E |
| ACM stuck in Pending validation | Validation CNAME not added or set to proxied | Set proxy status to grey cloud (DNS only) |
| Cloudflare Access not prompting | CNAME proxy status is grey | Set to orange cloud (Proxied) |
| `trading.yourdomain.com` not resolving | CloudFront alternate domain not configured | Complete Phase E step 2 |

---

## SentimentFeed — Dynamic Watchlist Fix

`SentimentFeed.jsx` originally had a hardcoded 14-ticker list and called `/sentiment/batch/scores` directly, bypassing the Schwab movers API entirely. Fixed in two parts:

1. Added `GET /api/ai/sentiment` endpoint in `routers/ai.py` — calls `load_context()` (which uses the Schwab dynamic watchlist) and returns just the `sentiment` array, with no Claude call, so it's fast.
2. Updated `SentimentFeed.jsx` to fetch from `/api/ai/sentiment` instead of the hardcoded call.

The Sentiment card now shows live movers (up to 18 tickers from SPX/Nasdaq/Dow via Schwab) plus any tickers currently held in the portfolio.

**Fix:**
```
npm i -g @anthropic-ai/claude-code
```
Run from VS Code PowerShell terminal. First run showed a cleanup warning (EPERM on `claude.exe` still locked). Second run after closing Claude Code = clean, no errors. Auto-update banner gone.

**Key gotcha:** Close Claude Code before running the reinstall if you see the EPERM cleanup warning.

---