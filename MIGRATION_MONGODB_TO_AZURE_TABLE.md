# Migration Plan: MongoDB → Azure Table Storage (with MongoDB abstraction kept)

**Date:** 2026-04-20  
**Author:** Engineering  
**Status:** Approved — implementation follows in next commit

---

## Why This Migration

MongoDB was introduced to store `GenerationSession` records so the image quality
evaluator could discover all generated images without scanning the entire blob container.

However:
- You have no MongoDB subscription
- Setting up and maintaining a MongoDB Atlas cluster adds cost and operational complexity
- **You already have Azure Storage** — the same account used for blob storage

Azure Table Storage is built into every Azure Storage Account. It requires:
- No separate subscription
- No new credential
- No new SDK package (the `azure-data-tables` package is already available with `azure-storage-blob`)
- No migration of existing data — it starts empty and fills as new generations run

---

## What MongoDB Was Being Used For

MongoDB was used in **two places**:

### 1. `POST /api/generate` — write a GenerationSession after PDF is ready

Stores: `generation_id`, `child_name`, `story_id`, `gender`, `generation_mode`,
`status`, `pdf_blob_path`, `pdf_filename`, `page_results[]` (with `blob_path` per page),
`pages_succeeded`, `pages_failed`, `total_pages`, `completed_at`

Purpose: gives the quality evaluator a structured index of all generated images
without needing to scan the blob container.

### 2. `GET/POST /api/status` in `server.py` — a legacy status-check endpoint

Stores generic `{client_name, timestamp}` records. This is a leftover from
the original project scaffold. It is **not used anywhere in the app or evaluator**.
It will be kept in code but MongoDB dependency will be removed from its hot path.

### 3. `tests/evaluator/blob_reader.py` — read GenerationSessions

Queries the collection to build a list of `GeneratedImageRecord` objects.
Falls back to blob scan today if MongoDB fails.

---

## Chosen Replacement: Azure Table Storage

### Why Azure Table Storage and not Azure Blob JSON files?

| Option | Query by child? | Query by story? | Sorted? | Cost |
|---|---|---|---|---|
| MongoDB | ✅ indexed | ✅ indexed | ✅ | Subscription needed |
| Azure Table Storage | ✅ PartitionKey filter | ✅ RowKey filter | ✅ by RowKey | Free in your existing account |
| Blob JSON files (one per session) | ❌ must list + download all | ❌ must list + download all | ❌ | Free but slow to query |

Azure Table Storage is a NoSQL key-value store built into every Azure Storage Account.
It supports filter expressions (`PartitionKey eq 'Niku'`, `RowKey gt '20260101'`)
that make it fast to query by child, story, or date range without downloading
all records.

### Table design

**Table name:** `GenerationSessions`

```
PartitionKey = child_name_safe      (e.g. "niku")
RowKey       = completed_at_gen_id  (e.g. "20260420_162530_abc12345")
               ─ ISO timestamp ensures natural sort order (newest last)
               ─ gen_id suffix ensures uniqueness

Additional columns (flat, all strings):
  generation_id, story_id, gender, generation_mode,
  status, pdf_blob_path, pdf_filename,
  pages_succeeded, pages_failed, total_pages,
  page_results_json   ← JSON-serialised list of {page_number, blob_path, succeeded}
```

**Query patterns supported:**
- All sessions for child "Niku" → filter `PartitionKey eq 'niku'`
- All sessions for story → filter `story_id eq 'forest_of_smiles'` (full table scan, acceptable at this scale)
- All sessions (evaluator) → list all rows, paginated

### Key-value table for Orders (future)

**Table name:** `Orders`

```
PartitionKey = user_mobile_safe
RowKey       = created_at_order_id
```

---

## Abstraction Design

A `SessionStore` interface will be introduced so the application is never
directly coupled to either MongoDB or Azure Table Storage:

```python
class SessionStore(ABC):
    async def write_session(self, session: GenerationSession) -> None: ...
    async def read_session(self, generation_id: str) -> dict | None: ...
    async def list_sessions(self, child_name=None, story_id=None, limit=1000) -> list[dict]: ...

class AzureTableSessionStore(SessionStore):   # ← implemented next commit
    """Uses Azure Table Storage. No extra subscription needed."""

class MongoSessionStore(SessionStore):         # ← kept as-is, used if MONGO_URL set
    """Uses MongoDB via Motor. Requires MONGO_URL env var."""

class NullSessionStore(SessionStore):          # ← no-op fallback
    """Does nothing. Used when no storage is configured."""
```

**Selection logic (in `server.py` startup):**
```
if AZURE_STORAGE_CONNECTION_STRING is set → AzureTableSessionStore (default when on Azure)
elif MONGO_URL is set and reachable      → MongoSessionStore
else                                     → NullSessionStore (evaluator falls back to blob scan)
```

This means:
- **Your production Azure deployment:** automatically uses Azure Table Storage (same connection string)
- **Anyone with MongoDB:** automatically uses MongoDB
- **Local dev with neither:** NullSessionStore (no crash, evaluator uses blob scan)

---

## What Changes

### New files
```
backend/core/session_store.py          ← SessionStore ABC + factory function
backend/core/azure_table_store.py      ← AzureTableSessionStore implementation
```

### Modified files
```
backend/server.py                      ← initialise session_store on startup
backend/routes/generate.py             ← replace direct MongoDB write with session_store.write_session()
tests/evaluator/blob_reader.py         ← replace pymongo with session_store.list_sessions()
backend/requirements.txt               ← add azure-data-tables; motor stays (optional dep)
```

### Not changed
```
backend/models/generation.py           ← GenerationSession model unchanged
backend/core/storage_paths.py          ← path functions unchanged
tests/evaluator/face_evaluator.py      ← evaluator logic unchanged
tests/evaluator/scene_metadata.py      ← scene metadata unchanged
tests/evaluator/run_evaluator.py       ← runner unchanged (uses blob_reader)
```

---

## Azure Setup Required

None. The Azure Table Storage is part of your existing Storage Account.
The SDK will create the `GenerationSessions` table automatically on first write.

No new portal configuration. No new credentials. The same
`AZURE_STORAGE_CONNECTION_STRING` already in your App Service settings is used.

---

## What MongoDB Code Becomes

`MongoSessionStore` remains fully implemented and usable. If you ever set
`MONGO_URL` in your environment, it takes precedence and MongoDB is used.
Nothing is deleted.

---

## Rollout Plan

1. **Commit 1 (this document):** Migration plan — reviewed and merged
2. **Commit 2:** Implement `SessionStore` ABC, `AzureTableSessionStore`,
   `MongoSessionStore`, update `generate.py`, `server.py`, `blob_reader.py`,
   `requirements.txt`
3. **Deploy to beta:** Azure Table Storage activates automatically.
   The `GenerationSessions` table appears in your Azure Storage Account.
   New storybook generations write to it. Evaluator discovers images from it.
4. **Verify:** Generate one storybook, check Azure Portal → Storage Account →
   Tables → `GenerationSessions`. Run `python tests/evaluator/run_evaluator.py --max-iter 1`.

---

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Azure Table write fails | Non-fatal — PDF still returned. Evaluator falls back to blob scan. |
| motor import fails (no MongoDB) | Already non-fatal in server.py. MongoSessionStore not instantiated if no MONGO_URL. |
| Existing sessions (none yet) | No data migration needed — table starts empty. |
| Table SDK not installed | Added to requirements.txt. Installed by Oryx at deploy time. |
