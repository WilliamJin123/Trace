# Task Management REST API - Specification

## Overview
A RESTful API for managing tasks with title, status, and assignee information.

## Data Model

### Task
```json
{
  "id": "uuid",
  "title": "string (required, 1-200 chars)",
  "status": "enum(todo, in_progress, done)",
  "assignee": "string or null (email format)",
  "created_at": "ISO-8601 timestamp",
  "updated_at": "ISO-8601 timestamp"
}
```

## Endpoints

### 1. Create Task
**POST /tasks**
- Request body: `{ title, assignee? }`
- Response: 201 Created with Task object (status defaults to "todo")

### 2. Get Task
**GET /tasks/{id}**
- Response: 200 OK with Task object, or 404 Not Found

### 3. List Tasks
**GET /tasks**
- Query params: `?status=todo&assignee=user@example.com&limit=50&offset=0`
- Response: 200 OK with paginated array of Task objects
- Default pagination: limit=50, offset=0

### 4. Update Task
**PATCH /tasks/{id}**
- Request body: `{ title?, status?, assignee? }` (partial updates)
- Response: 200 OK with updated Task object, or 404 Not Found

### 5. Delete Task
**DELETE /tasks/{id}**
- Response: 204 No Content, or 404 Not Found

## Status Transitions
- `todo` → `in_progress` → `done` (linear progression)
- Can transition back to `todo` from any state
- Invalid transitions rejected with 400 Bad Request

## Error Responses
| Code | Scenario |
|------|----------|
| 400 | Invalid request (validation, bad status transition) |
| 404 | Task not found |
| 409 | Conflict (e.g., invalid status transition) |
| 500 | Server error |

## Success Criteria
- All endpoints return correct status codes
- Pagination works correctly
- Status transitions enforced
- Data persisted and retrievable
- Assignee validation (email or null)
