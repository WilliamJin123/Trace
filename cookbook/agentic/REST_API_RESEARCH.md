# REST API Design: Research Findings
**Date**: 2026-03-17
**Status**: Complete research synthesis (3 domains)

---

## 1. Authentication Patterns

### Overview
Four primary authentication methods dominate modern REST API design. The choice depends on your use case: server-to-server (API Keys), user delegation (OAuth 2.0), stateless scaling (JWT), or simple access control (Basic Auth).

### Pattern 1: API Keys
**Best for**: Server-to-server communication, internal services
**How it works**: Static token passed in headers or query params
**Pros**:
- Simplest to implement
- Works well for trusted callers
- Low computational overhead

**Cons**:
- No expiration unless manually managed
- Compromised keys require regeneration
- Limited scope/permission granularity

**Implementation pattern**:
- Store in `Authorization: Bearer <key>` header
- Rotate keys regularly (monthly recommended)
- Use environment variables or secrets manager (never hardcode)

---

### Pattern 2: JWT (JSON Web Tokens)
**Best for**: Stateless distributed systems, microservices, user authentication
**How it works**: Self-contained tokens signed with secret/key, contains claims (user ID, roles, permissions)
**Pros**:
- Stateless (no server-side session storage)
- Scales horizontally across servers
- Token contains all needed info (permissions, scopes)
- Works well for mobile/SPA clients
- Self-validating (cryptographically signed)

**Cons**:
- Can't revoke instantly (token valid until expiration)
- Token payload visible (don't put secrets in claims)
- Requires proper secret management

**Implementation pattern**:
- Set short expiration (15-60 minutes)
- Use refresh tokens for longer sessions
- Validate signature on every request
- Store secret securely (not in code)
- Include: `sub` (user ID), `iat` (issued at), `exp` (expiration), custom claims for roles/scopes

---

### Pattern 3: OAuth 2.0
**Best for**: Third-party access, user delegation, social login integration
**How it works**: User grants limited access scope to third-party app without sharing credentials
**Pros**:
- Industry standard (used by Google, GitHub, Facebook)
- User never shares password with third party
- Limited, revocable scopes
- Works across platforms

**Cons**:
- Complex to implement fully
- Multiple flows (authorization code, implicit, client credentials, refresh token)
- Requires user interaction for new scopes

**Implementation pattern**:
- Use authorization code flow for web apps
- Use client credentials for service-to-service
- Include `client_id`, `client_secret`, `redirect_uri` in flow
- Return `access_token` (short-lived) + `refresh_token` (long-lived)
- Separate auth server from resource server

---

### Pattern 4: Mutual TLS (mTLS)
**Best for**: High-security internal APIs, certificate-based authentication
**How it works**: Both client and server present certificates; validated at transport layer
**Pros**:
- Cannot be man-in-the-middle'd
- Works below application layer
- Strongest available

**Cons**:
- Complex certificate management
- Requires PKI infrastructure
- Harder to test/debug

---

### 2025-2026 Recommended Strategy
Modern APIs typically use **layered authentication**:
1. **API Keys** for server-to-server (trusted, internal)
2. **OAuth 2.0** for user-facing third-party access
3. **JWT** for microservices and stateless backends
4. **mTLS** for high-security internal communication

Always:
- Use HTTPS (never HTTP)
- Rotate keys/tokens regularly
- Implement rate limiting per auth principal
- Centralize secret management (AWS Secrets Manager, HashiCorp Vault, etc.)
- Never log full tokens/keys in error messages

---

## 2. Database Schema Design

### Core Principles

**Normalization (up to 3NF)**
- Reduces data redundancy
- Enforces data integrity
- Standard for transactional data
- Trade-off: More JOINs needed at query time

**Strategic Denormalization**
- Add derived/pre-computed columns for read-heavy queries
- Duplicate data purposefully for hot access paths
- Common in OLAP, analytics, and caching layers
- Decision: Profile before denormalizing

**The Hybrid Approach** (recommended for high-traffic APIs)
- Normalize transactional data (user accounts, orders)
- Denormalize frequently accessed views (user stats, aggregates)
- Use caching layers (Redis) for read-heavy data
- Example: Normalize `users` + `orders` tables, denormalize `user_profile_stats` (pre-computed)

---

### Indexing Strategy (Most Critical for Performance)

**Indexes dramatically reduce query execution time.** For REST APIs, they're the single most important optimization after schema design.

**Types of indexes**:
1. **Single-column indexes**: For filtered/searched columns
   ```sql
   CREATE INDEX idx_users_email ON users(email);
   CREATE INDEX idx_orders_user_id ON orders(user_id);
   ```

2. **Composite indexes**: For multi-column WHERE/JOIN predicates
   ```sql
   CREATE INDEX idx_orders_user_date ON orders(user_id, created_at);
   ```

3. **Covering indexes**: Include all columns needed to answer query (avoids table access)
   ```sql
   CREATE INDEX idx_orders_covering ON orders(user_id) INCLUDE (total, status);
   ```

**Indexing rules for REST APIs**:
- Index columns in WHERE clauses
- Index foreign keys (for JOINs)
- Index sort columns (ORDER BY)
- Create composite indexes matching common query patterns
- Profile queries; don't guess (use EXPLAIN/ANALYZE)

---

### Connection Management

- Use connection pooling (don't create connection per request)
- Pool size: 10-30 for typical APIs, higher for high-concurrency services
- Configure idle timeout to prevent stale connections
- Example libraries: pgBouncer (PostgreSQL), MySQL connectors with pooling

---

### Scalability Patterns

**Read replicas**: For read-heavy workloads
- Master handles writes
- Replicas handle reads
- Slightly stale data acceptable for some queries

**Sharding**: For massive scale (billions of records)
- Horizontal partitioning by shard key (user_id, tenant_id)
- Each shard is an independent database
- Complexity: routing, cross-shard queries, rebalancing

**Partitioning**: For single-database scale
- Time-based: Archive old data (monthly/yearly partitions)
- Range-based: Partition by natural ranges (id ranges, geographic regions)
- List-based: Partition by category/status

**When to implement**:
- Single table exceeds 10M rows with high query volume
- Storage exceeds physical limits
- Query performance degradation despite indexing

---

### Data Type Selection

- Use **appropriate types** (INT not TEXT for numbers, DATE not TEXT for dates)
- Numeric types: TINYINT (0-255), INT (±2.1B), BIGINT (±9.2E18)
- Strings: VARCHAR(n) with max length, TEXT only if unbounded
- Dates: DATE (date only), TIMESTAMP/DATETIME (with time), use UTC
- Avoid nullable columns unless semantically meaningful
- Default values reduce NULL storage

---

### Schema Versioning

Plan for evolution:
- Add columns with sensible defaults (non-breaking)
- Avoid renaming/deleting columns (create new, deprecate old)
- Version your API separately from schema (schema can evolve without API version)
- Migrations: Test in staging, plan rollback, execute during low-traffic window

---

## 3. Error Handling

### HTTP Status Codes (Essential)

**2xx Success**
- `200 OK`: Request succeeded
- `201 Created`: Resource created successfully
- `204 No Content`: Successful, no response body

**3xx Redirection**
- `301 Moved Permanently`: Resource moved
- `304 Not Modified`: Client cache still valid

**4xx Client Error**
- `400 Bad Request`: Malformed request (validation failed)
- `401 Unauthorized`: Authentication missing/invalid
- `403 Forbidden`: Authenticated but insufficient permissions
- `404 Not Found`: Resource doesn't exist
- `409 Conflict`: State conflict (duplicate, stale data)
- `422 Unprocessable Entity`: Validation failed (semantic)
- `429 Too Many Requests`: Rate limited

**5xx Server Error**
- `500 Internal Server Error`: Unexpected error
- `503 Service Unavailable`: Temporarily down
- `504 Gateway Timeout`: Upstream timeout

**Critical rule**: Never return 500 for client mistakes. Return appropriate 4xx.

---

### Standardized Error Response Format

**RFC 7807 / RFC 9457 (Problem Details)** - Industry standard:

```json
{
  "type": "https://api.example.com/errors/validation-failed",
  "title": "Validation Failed",
  "status": 422,
  "detail": "The 'email' field is required",
  "instance": "/api/users",
  "code": "VALIDATION_ERROR",
  "errors": [
    {
      "field": "email",
      "message": "Email is required",
      "code": "REQUIRED"
    },
    {
      "field": "age",
      "message": "Age must be > 18",
      "code": "MIN_VALUE"
    }
  ],
  "timestamp": "2026-03-17T14:30:00Z",
  "requestId": "req-abc123def456"
}
```

**Minimal format** (if RFC 7807 too verbose):

```json
{
  "error": "VALIDATION_ERROR",
  "message": "Validation failed",
  "status": 422,
  "requestId": "req-abc123def456",
  "details": [
    {
      "field": "email",
      "reason": "required"
    }
  ]
}
```

---

### Key Error Handling Principles

**1. Clear, Actionable Messages**
- **Bad**: "Invalid input"
- **Good**: "Email must be valid format (user@example.com)"
- **Better**: "Email 'john@' is invalid format (user@example.com)"

**2. Include Unique RequestId**
- Enables tracing in logs: `"requestId": "req-abc123def456"`
- Client provides in follow-up support requests
- Correlates logs across microservices

**3. Never Leak Sensitive Information**
- Don't expose database errors: "Column 'password_hash' cannot be null"
- Don't expose file paths, internal IPs, library versions
- Do describe the problem: "Password is required"

**4. Consistent Structure Across All Endpoints**
- Same error format for all errors
- Same field names, same type of values
- Makes client parsing predictable

**5. Implement Retry Logic (Client-side)**
- Retry 5xx errors with exponential backoff
- Don't retry 4xx errors (they'll fail again)
- Max retries: 3-5, with jitter to avoid thundering herd

**6. Centralized Error Handling**
- Map exceptions to HTTP responses in middleware
- Prevent internal error details leaking
- Consistent logging for debugging

---

### Implementation Patterns

**Validation Errors**
```json
{
  "status": 422,
  "error": "VALIDATION_ERROR",
  "message": "Request validation failed",
  "fields": {
    "email": ["Invalid email format"],
    "age": ["Must be >= 18"]
  }
}
```

**Authentication/Authorization Errors**
```json
{
  "status": 401,
  "error": "UNAUTHORIZED",
  "message": "Authentication required",
  "code": "AUTH_REQUIRED"
}
```

**Resource Not Found**
```json
{
  "status": 404,
  "error": "NOT_FOUND",
  "message": "User with id '123' not found",
  "resourceType": "User",
  "resourceId": "123"
}
```

**Rate Limiting**
```json
{
  "status": 429,
  "error": "RATE_LIMITED",
  "message": "Too many requests",
  "retryAfter": 60
}
```

---

### Logging & Monitoring

- Log errors with context: timestamp, requestId, user ID, endpoint
- Monitor 5xx rate: alert if > 1%
- Track 4xx patterns: unusual 404s may indicate API misuse
- Set up alerting for specific codes: 503, 500 (immediate), 422 patterns
- Use structured logging (JSON) for parsing

---

## Summary: Recommended Stack

| Aspect | Choice | Rationale |
|--------|--------|-----------|
| **Authentication** | JWT + API Keys (layered) | JWT for users, API Keys for service-to-service |
| **Normalization** | 3NF transactional + denormalized views | Balance integrity with performance |
| **Indexing** | Composite indexes on hot queries | Single most important optimization |
| **Error Format** | RFC 7807 Problem Details | Industry standard, client-compatible |
| **Status Codes** | Proper 4xx/5xx mapping | No generic 500s for client errors |
| **Rate Limiting** | Token bucket per auth principal | Fair usage, prevent abuse |

---

## Implementation Readiness

✅ Research complete across all three domains
✅ Trade-offs documented
✅ Best practices synthesized
⏳ Ready for implementation planning

**Next step**: Review findings, approve approach, then transition to implementation phase.

---

### Sources

**Authentication**:
- [REST API Authentication: 4 Methods Compared (2026 Guide)](https://www.knowi.com/blog/4-ways-of-rest-api-authentication-methods/)
- [7 REST API Authentication Methods Explained for 2025](https://refgrow.com/blog/rest-api-authentication-methods)
- [What Is API Authentication? OAuth 2.0, JWT, and key methods](https://workos.com/blog/what-is-api-authentication-a-guide-to-oauth-2-0-jwt-and-key-methods)
- [API Authentication Best Practices in 2026](https://blog.apiverve.com/post/api-authentication-best-practices/)

**Database Schema**:
- [Database Schema Design for Scalability: Best Practices](https://dev.to/dhanush___b/database-schema-design-for-scalability-best-practices-techniques-and-real-world-examples-for-ida)
- [Schema Design Best Practices for Scalable Databases](https://medium.com/@nileshsharma_4675/schema-design-best-practices-for-scalable-databases-eb5239679d0f)
- [Top 10 Database Schema Design Best Practices](https://www.bytebase.com/blog/top-database-schema-design-best-practices/)
- [Database Normalization Explained](https://www.dbdesigner.net/database-normalization-explained-how-to-design-clean-scalable-schemas/)

**Error Handling**:
- [Best Practices for REST API Error Handling](https://www.baeldung.com/rest-api-error-handling-best-practices)
- [REST API Design Best Practices (2026)](https://www.codebrand.us/blog/rest-api-design-best-practices-2026/)
- [Best Practices for API Error Handling - Postman Blog](https://blog.postman.com/best-practices-for-api-error-handling/)
- [How to Design Error Responses in REST APIs](https://oneuptime.com/blog/post/2026-01-27-rest-api-error-responses/view)
