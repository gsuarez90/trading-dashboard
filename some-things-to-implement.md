## Pre-Build Setup Instructions

- Reference C:\Users\lcplu\source\repos\myPortfolioRevision for all transfer overs listed below

### Repository
- No GitHub repo provisioned yet — create a new repo named
  `trading-dashboard` as the first step
- Initialize with a .gitignore for Python and Node
- Do not commit .env.local under any circumstances

### GitHub Actions — Transfer from myPortfolioRevision
- Transfer Claude Code Review workflow
- Transfer Claude PR Assistant workflow
- Adapt Frontend Deploy workflow for dual S3/CloudFront deployment
  (public synthetic portfolio + private live portfolio, separate
  env vars and CloudFront distribution IDs per deployment)
- Add Backend Deploy workflow via AWS SAM
  (sam build + sam deploy on push to main)
- Add Python linting/formatting workflow (Black + isort) on every PR
- Add pytest workflow — runs tests/test_guardrails.py on every PR,
  blocks merge if any test fails

### Skills — Transfer from myPortfolioRevision
- commit skill — add pre-commit hook to run pytest before staging
- log skill — append session notes to notes.md
- wrap skill — save session summary to memory at end of each session
- Add new env-check skill — verifies all required .env.local keys
  are populated before starting a build session

### Python Environment
- Python 3.13
- Use Black for formatting, isort for import sorting
- requirements.txt for backend dependencies
- package.json for frontend dependencies

### Important Notes
- Do not use C# — Python 3.13 throughout
- Follow build order in kickoff prompt sequentially
- Do not skip guardrail tests at step 7
- All secrets go in AWS SSM Parameter Store, never in code
- .env.local is gitignored — never committed
