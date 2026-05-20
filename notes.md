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
