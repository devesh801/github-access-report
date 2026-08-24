# GitHub Organization Access Report Service - Assignment Submission

**Candidate Repository URL**: [https://github.com/devesh801/github-access-report](https://github.com/devesh801/github-access-report)  
**Technology Stack**: Python 3.10+, FastAPI, Pydantic v2, HTTPX (Async), Pytest, Docker  

---

## 1. Problem Statement & Objective

Organizations require clear visibility into who has access to which repositories in GitHub to ensure least-privilege access control, audit compliance (SOC 2, ISO 27001), and mitigate security risks.

This service connects to GitHub, retrieves repositories and collaborator access permissions for a given organization at scale (handling **100+ repositories and 1,000+ users**), aggregates the data into a clean `User -> Repositories` mapping with highest-privilege ranking, and exposes a high-performance REST API.

---

## 2. How Authentication is Configured

The service supports three secure authentication mechanisms:

### 1. Personal Access Token (PAT)
Set the `GITHUB_TOKEN` environment variable in the `.env` file:
```ini
GITHUB_TOKEN=ghp_yourTokenHere
```
- **Classic Token Scopes**: `repo`, `read:org`
- **Fine-Grained Token Permissions**: Read-only access to Organization Members/Admin & Repository Metadata/Admin.

### 2. GitHub App Authentication (Enterprise Standard)
Supports RS256 JWT generation using private keys and automatic exchange for short-lived Installation Access Tokens:
```ini
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=78901234
GITHUB_APP_PRIVATE_KEY=./private-key.pem
```

### 3. Per-Request Header Authorization (Multi-Tenant)
Callers can provide their own organization token per request via HTTP headers, overriding the server default:
- `Authorization: Bearer <token>`
- `X-GitHub-Token: <token>`

---

## 3. How to Run the Project

### Option A: Local Run (Python)
```bash
# 1. Clone repository
git clone https://github.com/devesh801/github-access-report.git
cd github-access-report

# 2. Set up virtual environment
python -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Add your GITHUB_TOKEN in .env

# 5. Start the service
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
The server will start at `http://localhost:8000`.

### Option B: Docker Container
```bash
docker build -t github-access-report:latest .
docker run -d -p 8000:8000 -e GITHUB_TOKEN=ghp_yourTokenHere github-access-report:latest
```

### Option C: Docker Compose
```bash
docker compose up -d
```

---

## 4. How to Call the API Endpoints

### 1. Generate Organization Access Report
`GET /api/v1/orgs/{org}/access-report`

**cURL Example:**
```bash
curl -X GET "http://localhost:8000/api/v1/orgs/devesh801/access-report" \
  -H "Authorization: Bearer <GITHUB_TOKEN>"
```

**PowerShell Example:**
```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/orgs/devesh801/access-report" | ConvertTo-Json -Depth 6
```

**Sample JSON Output:**
```json
{
  "organization": "devesh801",
  "generated_at": "2026-08-24T19:32:07.347707",
  "cached": false,
  "execution_time_seconds": 0.579,
  "collector_used": "graphql",
  "summary": {
    "total_repositories": 8,
    "total_users": 1,
    "private_repositories": 0,
    "public_repositories": 8,
    "permission_distribution": {
      "ADMIN": 1,
      "MAINTAIN": 0,
      "WRITE": 0,
      "TRIAGE": 0,
      "READ": 0
    }
  },
  "users": [
    {
      "login": "devesh801",
      "total_repositories_accessible": 8,
      "highest_permission": "ADMIN",
      "repositories": [
        {
          "name": "AI-Decision-Intelligence-Platform",
          "full_name": "devesh801/AI-Decision-Intelligence-Platform",
          "is_private": false,
          "permission": "ADMIN",
          "raw_permission": "ADMIN",
          "affiliation": "DIRECT",
          "url": "https://github.com/devesh801/AI-Decision-Intelligence-Platform"
        }
      ]
    }
  ]
}
```

### 2. Available Query Filters
- **Filter by Minimum Permission**: `?min_permission=WRITE` (filters for `WRITE`, `MAINTAIN`, or `ADMIN`)
- **Filter by Specific User**: `?user=octocat`
- **Filter by Specific Repository**: `?repository=core-backend`
- **Filter by Affiliation**: `?affiliation=OUTSIDE` (or `DIRECT`, `ALL`)
- **Force Fresh Live Fetch (Bypass Cache)**: `?refresh=true`

### 3. Additional Endpoints
- `GET /api/v1/orgs/{org}/users`: Quick list of users and access counts.
- `GET /api/v1/orgs/{org}/repos`: Quick list of repositories and collaborator counts.
- `GET /health`: Health check and live GitHub rate-limit quota inspection.
- `GET /docs`: Interactive Swagger UI documentation.

---

## 5. Scale Strategy (100+ Repositories, 1,000+ Users)

A naive sequential REST approach ($1 + N$ queries) would take $30\text{--}60$ seconds and risk rate-limit exhaustion. Our solution handles enterprise scale efficiently:

1. **Batched GraphQL Collector (Primary Engine)**:
   - Fetches up to 50 repositories and 100 collaborators per repository in **single GraphQL round-trips**.
   - An organization with 100 repositories is retrieved in just **2 network round-trips** (costing only 2 GraphQL points against the 5,000/hr quota).
2. **Bounded Asynchronous Concurrency (`asyncio.Semaphore(10)`)**:
   - For repositories with $>100$ collaborators, deep pages are fetched concurrently via a worker pool bounded to 10 parallel connections to avoid triggering GitHub's anti-abuse secondary rate limits.
3. **Adaptive Rate Limiting & Backoff**:
   - Monitors `x-ratelimit-remaining`, `x-ratelimit-reset`, and `retry-after` headers in real time.
   - Automatically pauses and retries with jittered exponential backoff if a 429 or secondary rate limit occurs.
4. **In-Memory TTL Caching**:
   - Caches organization reports (5-minute TTL default) with thread-safe eviction, serving repeated queries in sub-10ms latency.

---

## 6. Assumptions & Design Decisions

1. **Inverted View as Primary Schema**: Transforming repository-centric permissions into a user-centric view (`User -> Repositories`) provides immediate clarity on individual access footprints and privilege creep.
2. **Permission Normalization & Hierarchy**: GitHub REST and GraphQL use varying permission terms (`admin`, `push`, `pull`, `maintain`, `triage`, `ADMIN`, `WRITE`, `READ`). We normalize these into a unified hierarchy (`ADMIN` > `MAINTAIN` > `WRITE` > `TRIAGE` > `READ`) to deterministically compute each user's highest permission.
3. **Multi-Tenant Token Support**: Allowing tokens to be passed via request headers enables a single deployment to serve multiple organizations securely.
4. **Dual Collector Architecture**: GraphQL provides optimal speed and quota efficiency; an async REST collector fallback ensures operational resilience.

---

## 7. Testing & Quality Assurance

- **32 Automated Tests** covering unit aggregation logic, GraphQL batch pagination, REST fallback, rate limiting, and FastAPI endpoints.
- **85% Test Coverage** achieved.
- Run tests via: `pytest -v --cov=app --cov-report=term-missing`
