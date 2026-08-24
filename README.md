# GitHub Organization Access Report Service

A high-performance, resilient microservice designed to audit and report user repository permissions across GitHub organizations at enterprise scale (**100+ repositories, 1,000+ users**).

The service securely authenticates with GitHub, efficiently collects and aggregates repository access permissions, and exposes a structured REST API with filtering, caching, and analytics capabilities.

---

## Table of Contents

- [Features](#features)
- [Architecture & Scalability](#architecture--scalability)
- [Authentication Methods](#authentication-methods)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Local Setup](#local-setup)
  - [Running with Docker](#running-with-docker)
  - [Running with Docker Compose](#running-with-docker-compose)
- [API Reference](#api-reference)
  - [1. Organization Access Report](#1-organization-access-report)
  - [2. Organization Users Index](#2-organization-users-index)
  - [3. Organization Repositories Index](#3-organization-repositories-index)
  - [4. Health Check & Rate Limit Status](#4-health-check--rate-limit-status)
  - [5. Clear Cache](#5-clear-cache)
  - [Interactive Swagger / OpenAPI Docs](#interactive-swagger--openapi-docs)
- [Filtering Capabilities](#filtering-capabilities)
- [Design Decisions & Assumptions](#design-decisions--assumptions)
- [Testing & Quality Assurance](#testing--quality-assurance)

---

## Features

- **Enterprise Scale Support**: Handles organizations with hundreds of repositories and thousands of users in seconds using batched GraphQL queries and bounded asynchronous worker pools.
- **Inverted Aggregation (User $\rightarrow$ Repositories)**: Transforms repository-level collaborator permissions into a clear, unified user-centric access mapping.
- **Permission Hierarchy**: Computes each user's highest effective privilege level (`ADMIN` > `MAINTAIN` > `WRITE` > `TRIAGE` > `READ`).
- **Flexible Authentication**: Supports Classic Personal Access Tokens (PAT), Fine-Grained Tokens, GitHub App authentication (RS256 JWT exchange), and per-request header overrides.
- **Resilience & Rate Limit Management**: Proactively tracks GitHub rate limit headers (`x-ratelimit-remaining`, `x-ratelimit-reset`, `retry-after`) and applies exponential backoff with jitter on HTTP 429 and secondary rate limits.
- **In-Memory TTL Caching**: Caches organization scan results with thread-safe eviction to serve repeat requests with sub-10ms latency, with support for live cache busting (`?refresh=true`).
- **Dual Collection Engines**: Primary batched GraphQL engine with an asynchronous REST API fallback.
- **Interactive Documentation**: Auto-generated OpenAPI / Swagger UI at `/docs` and ReDoc at `/redoc`.

---

## Architecture & Scalability

### The Challenge of Scale (100+ Repos, 1000+ Users)

A naive implementation that issues sequential REST API calls (`GET /orgs/{org}/repos` followed by `GET /repos/{owner}/{repo}/collaborators` for every repository) suffers from:
1. **$O(N)$ Sequential Latency**: Scanning 100+ repositories sequentially takes $100 \times 300\text{ms} \approx 30\text{--}60\text{s}$.
2. **Rate Limit Exhaustion**: Standard GitHub tokens have a rate limit of 5,000 requests/hour. Multi-page collaborator lists on active repos quickly drain the quota.
3. **Secondary Rate Limits**: Spawning unthrottled bursts of concurrent HTTP calls triggers GitHub's anti-abuse and secondary rate limit blocks.

### The Solution

```mermaid
flowchart TD
    Client[API Client] -->|GET /api/v1/orgs/{org}/access-report| FastAPIServer[FastAPI Service]
    FastAPIServer --> CacheCheck{In-Memory TTL Cache?}
    CacheCheck -- Hit --> CachedResponse[Return Cached JSON Report]
    CacheCheck -- Miss --> CollectorRouter{Collector Strategy}
    
    CollectorRouter -- Primary --> GraphQLCollector[GraphQL Batch Collector]
    CollectorRouter -- Fallback --> RestCollector[Async REST Collector]
    
    GraphQLCollector -->|Batch 50 repos + 100 collabs/query| GitHubGraphQL[GitHub GraphQL API v4]
    GitHubGraphQL -->|Deep Pagination if >100 collabs| WorkerPool[Async Worker Pool (Semaphore=10)]
    WorkerPool --> GitHubGraphQL
    
    GraphQLCollector --> Aggregator[Access Report Aggregator]
    RestCollector --> Aggregator
    
    Aggregator -->|Normalize & Invert: User -> Repos| Report[Structured Access Report]
    Report --> SetCache[Store in TTL Cache]
    SetCache --> Response[Return JSON Access Report]
```

1. **GraphQL Batching (Primary Engine)**:
   - Queries 50 repositories and up to 100 collaborators per repository in a **single GraphQL round-trip** (costing only 1 point against GitHub's 5,000 GraphQL point quota).
   - An organization with 100 repositories is retrieved in just 2 network round-trips.
2. **Bounded Asynchronous Deep Pagination (`asyncio.Semaphore`)**:
   - When a repository has $>100$ collaborators, remaining pages are fetched concurrently via a worker pool limited to `MAX_CONCURRENT_REQUESTS=10`, optimizing throughput without hitting GitHub concurrency thresholds.
3. **Adaptive Backoff & Rate Limit Tracking**:
   - `GitHubRateLimitTracker` inspects response headers in real-time. If a 429 or secondary rate limit occurs, requests automatically back off with jittered exponential retry.
4. **Sub-millisecond Cached Reads**:
   - Cached responses bypass GitHub API round-trips entirely.

---

## Authentication Methods

The service supports three secure authentication strategies:

### 1. Personal Access Token (PAT)
Set the `GITHUB_TOKEN` environment variable in your `.env` file or environment.
- **Classic Token Scopes**: `read:org`, `repo`
- **Fine-Grained Token Permissions**: `Organization permissions: Read-only (Members, Administration)`, `Repository permissions: Read-only (Metadata, Administration)`

```bash
GITHUB_TOKEN=ghp_yourPersonalAccessTokenHere
```

### 2. GitHub App Authentication (Enterprise Standard)
Configure the GitHub App credentials in `.env`:
```bash
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=78901234
GITHUB_APP_PRIVATE_KEY=./private-key.pem
# Or inline PEM:
# GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
```
The service automatically generates RS256-signed JWTs and exchanges them for short-lived Installation Access Tokens, auto-refreshing them prior to expiration.

### 3. Per-Request Header Authorization
API clients can provide their own organization-scoped GitHub token directly in the request headers. This allows a single deployment of this service to be used multi-tenant across different teams or organizations:

```bash
# Using Authorization Header
curl -H "Authorization: Bearer ghp_userSpecificToken" \
  http://localhost:8000/api/v1/orgs/acme-corp/access-report

# Or using X-GitHub-Token Header
curl -H "X-GitHub-Token: ghp_userSpecificToken" \
  http://localhost:8000/api/v1/orgs/acme-corp/access-report
```

---

## Getting Started

### Prerequisites
- Python 3.10+ (or Docker)
- A GitHub Personal Access Token or GitHub App credentials

### Local Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-username/github-access-report.git
   cd github-access-report
   ```

2. **Create and activate a virtual environment**:
   ```bash
   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate

   # Windows
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env and insert your GITHUB_TOKEN
   ```

5. **Start the service**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
   The service will be live at `http://localhost:8000`.

---

### Running with Docker

Build and run the containerized application:

```bash
# Build the Docker image
docker build -t github-access-report:latest .

# Run the container
docker run -d -p 8000:8000 \
  -e GITHUB_TOKEN=ghp_yourPersonalAccessTokenHere \
  --name github-access-report-svc \
  github-access-report:latest
```

---

### Running with Docker Compose

```bash
# 1. Populate .env with your GITHUB_TOKEN
# 2. Launch container
docker compose up -d
```

---

## API Reference

### 1. Organization Access Report

Generates the complete aggregated report mapping users to all repositories they can access.

`GET /api/v1/orgs/{org}/access-report`

#### Parameters

| Parameter | Type | In | Default | Description |
|---|---|---|---|---|
| `org` | `string` | Path | *Required* | GitHub organization name (e.g. `github`, `acme`) |
| `min_permission` | `string` | Query | `None` | Minimum permission level: `READ`, `TRIAGE`, `WRITE`, `MAINTAIN`, `ADMIN` |
| `user` | `string` | Query | `None` | Filter by specific GitHub username |
| `repository` | `string` | Query | `None` | Filter to users who have access to this repository |
| `affiliation` | `string` | Query | `ALL` | Filter collaborator affiliation: `ALL`, `DIRECT`, `OUTSIDE` |
| `include_summary` | `boolean` | Query | `true` | Include aggregate metrics and permission distribution |
| `refresh` | `boolean` | Query | `false` | Bypass server cache and collect fresh data |
| `collector` | `string` | Query | `graphql` | Collector engine: `graphql` (fast, default) or `rest` |

#### Sample Request

```bash
curl -X GET "http://localhost:8000/api/v1/orgs/acme-corp/access-report?min_permission=WRITE" \
  -H "Authorization: Bearer ghp_yourToken"
```

#### Sample Response

```json
{
  "organization": "acme-corp",
  "generated_at": "2026-08-25T00:50:00.123456",
  "cached": false,
  "execution_time_seconds": 1.284,
  "collector_used": "graphql",
  "summary": {
    "total_repositories": 120,
    "total_users": 1050,
    "private_repositories": 45,
    "public_repositories": 75,
    "permission_distribution": {
      "ADMIN": 42,
      "MAINTAIN": 78,
      "WRITE": 610,
      "TRIAGE": 40,
      "READ": 280
    }
  },
  "users": [
    {
      "login": "alice",
      "name": "Alice Smith",
      "avatar_url": "https://avatars.githubusercontent.com/u/1",
      "html_url": "https://github.com/alice",
      "total_repositories_accessible": 2,
      "highest_permission": "ADMIN",
      "repositories": [
        {
          "name": "core-backend",
          "full_name": "acme-corp/core-backend",
          "is_private": true,
          "permission": "ADMIN",
          "raw_permission": "ADMIN",
          "affiliation": "DIRECT",
          "url": "https://github.com/acme-corp/core-backend",
          "description": "Core backend services"
        },
        {
          "name": "infra-terraform",
          "full_name": "acme-corp/infra-terraform",
          "is_private": true,
          "permission": "WRITE",
          "raw_permission": "WRITE",
          "affiliation": "TEAM",
          "url": "https://github.com/acme-corp/infra-terraform",
          "description": "Infrastructure as code"
        }
      ]
    },
    {
      "login": "bob",
      "name": "Bob Jones",
      "avatar_url": "https://avatars.githubusercontent.com/u/2",
      "html_url": "https://github.com/bob",
      "total_repositories_accessible": 1,
      "highest_permission": "WRITE",
      "repositories": [
        {
          "name": "frontend-app",
          "full_name": "acme-corp/frontend-app",
          "is_private": false,
          "permission": "WRITE",
          "raw_permission": "WRITE",
          "affiliation": "DIRECT",
          "url": "https://github.com/acme-corp/frontend-app",
          "description": "Web client app"
        }
      ]
    }
  ]
}
```

---

### 2. Organization Users Index

Returns a summary list of all users possessing access across organization repositories.

`GET /api/v1/orgs/{org}/users`

```bash
curl http://localhost:8000/api/v1/orgs/acme-corp/users
```

---

### 3. Organization Repositories Index

Returns an index of all repositories in the organization with collaborator counts.

`GET /api/v1/orgs/{org}/repos`

```bash
curl http://localhost:8000/api/v1/orgs/acme-corp/repos
```

---

### 4. Health Check & Rate Limit Status

Inspects service health, configuration state, and real-time GitHub rate-limit quota.

`GET /health` or `GET /api/v1/health`

#### Sample Response

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "auth_configured": true,
  "auth_type": "PAT",
  "github_reachable": true,
  "rate_limit": {
    "limit": 5000,
    "remaining": 4920,
    "reset_at": 1787612400,
    "seconds_until_reset": 3120.4,
    "resource": "graphql"
  }
}
```

---

### 5. Clear Cache

Purges all entries from the in-memory TTL cache.

`POST /api/v1/cache/clear`

---

### Interactive Swagger / OpenAPI Docs

Navigate to `http://localhost:8000/docs` in your browser to interact with the API using Swagger UI, or `http://localhost:8000/redoc` for ReDoc format.

---

## Filtering Capabilities

| Query Scenario | Example Query |
|---|---|
| Filter for Administrators only | `/api/v1/orgs/my-org/access-report?min_permission=ADMIN` |
| Filter for Write or higher access | `/api/v1/orgs/my-org/access-report?min_permission=WRITE` |
| Audit access for specific user | `/api/v1/orgs/my-org/access-report?user=octocat` |
| View who can access a repository | `/api/v1/orgs/my-org/access-report?repository=payments-service` |
| Outside collaborators only | `/api/v1/orgs/my-org/access-report?affiliation=OUTSIDE` |
| Force fresh live fetch (bypass cache) | `/api/v1/orgs/my-org/access-report?refresh=true` |

---

## Design Decisions & Assumptions

1. **GraphQL as Primary Collection Engine**:
   - GitHub GraphQL API v4 allows fetching repositories and their collaborators in unified nested queries. This cuts the number of required API calls by over 90% compared to sequential REST requests, enabling large organizations to be scanned in 1–2 seconds without rate limit issues.
2. **Permission Normalization & Ranking**:
   - Permissions across GitHub REST (`admin`, `push`, `pull`, `maintain`, `triage`) and GraphQL (`ADMIN`, `MAINTAIN`, `WRITE`, `TRIAGE`, `READ`) are normalized into a unified `PermissionLevel` enum with strict hierarchical comparison (`ADMIN` > `MAINTAIN` > `WRITE` > `TRIAGE` > `READ`).
3. **In-Memory TTL Caching**:
   - Access reports are cached for 5 minutes (configurable via `CACHE_TTL_SECONDS`). This protects GitHub rate limits during repeated dashboards or audit queries while allowing immediate cache bypass via `?refresh=true`.
4. **Bounded Concurrency Semaphore**:
   - Concurrency is throttled to 10 concurrent requests by default (`MAX_CONCURRENT_REQUESTS=10`) using `asyncio.Semaphore` to stay safely below GitHub's anti-abuse secondary rate limits.
5. **Multi-Tenant Token Flexibility**:
   - In addition to environment configuration, callers can supply their own GitHub token in the `Authorization` or `X-GitHub-Token` header, allowing a single service instance to safely serve multiple organizations with different access privileges.

---

## Testing & Quality Assurance

The codebase includes a comprehensive automated test suite with unit, integration, and mocking tests:

```bash
# Run pytest with short traceback
pytest -v --tb=short

# Run tests with code coverage report
pytest -v --cov=app --cov-report=term-missing
```

### Test Coverage Highlights
- **Aggregation Logic**: Tests user grouping, repository permission mapping, highest rank calculation, and filter combinations.
- **GraphQL Collector**: Mocks multi-page repository pagination and concurrent deep collaborator pagination.
- **REST Collector**: Tests fallback collection and permission parsing.
- **Rate Limiting & Backoff**: Verifies header parsing, reset time calculation, and jittered exponential backoff.
- **Authentication**: Validates PAT resolution, header overrides, RSA JWT generation, and missing credential error handling.
- **API Endpoints**: Tests all FastAPI endpoints, response formatting, status codes, and error scenarios (401, 403, 404, 429).
