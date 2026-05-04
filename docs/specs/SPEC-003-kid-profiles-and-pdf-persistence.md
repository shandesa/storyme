# StoryMe — Kid Profiles & PDF Persistence Specification

**Document ID:** SPEC-003  
**Version:** 1.0  
**Date:** 2026-05-01  
**Status:** Ready for Implementation  
**Branch target:** `beta`  

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Assumptions & Clarifications](#2-assumptions--clarifications)
3. [Scope & Non-Scope](#3-scope--non-scope)
4. [Architecture Overview](#4-architecture-overview)
5. [Data Models](#5-data-models)
6. [Storage Paths](#6-storage-paths)
7. [Backend — Kid Profile Store](#7-backend--kid-profile-store)
8. [Backend — Generated Book Store](#8-backend--generated-book-store)
9. [Backend — API Routes](#9-backend--api-routes)
10. [Backend — Generation Flow Changes](#10-backend--generation-flow-changes)
11. [Frontend — Home Page Changes](#11-frontend--home-page-changes)
12. [Frontend — Resume Flow](#12-frontend--resume-flow)
13. [No-Regression Boundary](#13-no-regression-boundary)
14. [Test Cases](#14-test-cases)
15. [Implementation Order](#15-implementation-order)
16. [Files Modified Summary](#16-files-modified-summary)

---

## 1. Problem Statement

### 1.1 Current Bugs

**Bug 1 — Session loss destroys generation context.**  
The inactivity timer (10 minutes) logs the user out. On re-login the user lands
on `/home` in INPUT step with no memory of their previous generation. They must
re-upload the child's photo and re-enter the name to regenerate.

**Bug 2 — No PDF retrieval after logout.**  
If the user generates a PDF, reaches the options page, and is then logged out by
inactivity before clicking "Download" — the PDF is gone from their perspective.
There is no way to retrieve it without restarting the entire generation.

### 1.2 Required Solution

1. **Kid Profiles** — A user can create named profiles for each child. Each
   profile stores the child's photo permanently. No re-upload is required when
   generating a new story for the same child.

2. **PDF Persistence** — Once a PDF is generated for a `(user, profile, story)`
   combination, the result is stored in the database. On re-login, the user is
   offered a direct link to download the PDF they had not yet downloaded.

---

## 2. Assumptions & Clarifications

The following assumptions are made where the requirements were ambiguous. These
should be reviewed and confirmed before implementation begins.

| # | Assumption | Impact if wrong |
|---|------------|----------------|
| A1 | One primary photo per kid profile (used for generation). Multiple additional photos are out of scope for this iteration. | Photo upload UI would need extending |
| A2 | Updating a profile photo does NOT automatically invalidate previously generated PDFs. The old PDF remains downloadable. | Would require cascade invalidation logic |
| A3 | A single profile can generate one book per story. Regenerating replaces the existing book record for that `(profile, story)` pair. | Would need to store multiple versions per pair |
| A4 | "Downloaded" means the user explicitly clicked the download link at least once. We track a `download_count` integer. | Could be defined as "file was saved locally" — unverifiable |
| A5 | The resume banner on the home page shows only the **most recent** undownloaded completed book across all profiles. | Could show all undownloaded books |
| A6 | Maximum 5 kid profiles per user account. | Arbitrary — can be changed via config |
| A7 | Profile deletion is soft on PDFs: the KidProfile record is hard-deleted, but the PDF blob in storage is retained for 30 days. GeneratedBook records are retained as order history. | Immediate cleanup would require blob deletion jobs |
| A8 | Gender options are exactly: `male`, `female`, `neutral` — matching the existing `VALID_GENDERS` set in `storage_paths.py`. | No new gender values |
| A9 | Age is an integer (years), minimum 0, maximum 12. Optional field — can be blank. | Age as range, DOB, etc. |
| A10 | The existing generate flow (upload photo ad-hoc, no profile) continues to work unchanged. Profiles are additive. | Breaking existing non-profile flow |
| A11 | Email delivery for PDF: if the user selects "Email PDF" and then logs out, the email is still sent by the backend async task (existing behaviour). No change needed. | Would need additional email resume logic |

---

## 3. Scope & Non-Scope

### In Scope

- Kid profile CRUD (create, read, update, delete)
- Profile photo upload and storage (permanent blob, not transient)
- Generated book record per `(user_mobile, profile_id, story_id)`
- Download count tracking on generated books
- Resume banner on home page for undownloaded completed books
- New generation flow: select profile → no re-upload needed
- New backend API routes under `/api/v2/kids/` and `/api/v2/books/`
- Two new Azure Tables: `KidProfiles`, `GeneratedBooks`
- New blob storage path prefix: `profiles/`

### Out of Scope (explicit exclusions)

- Multiple photos per kid profile
- Cosmetic redesign of any existing page
- Payment flow changes
- Print order changes
- Admin panel changes
- Push notifications or email on resume
- PDF sharing between users
- Story history / browsing (only most recent undownloaded book shown)
- Deletion of PDF blobs from storage (retention policy handled separately)
- Modifying the face image pipeline (covered by SPEC-002)

---

## 4. Architecture Overview

### 4.1 Current Flow

```
[Login] → [HomePage INPUT] → upload photo + name → [preview] →
  [FORMAT_SELECT] → [PaymentPage] → PDF generated → download
  (if logout before download: everything lost)
```

### 4.2 New Flow

```
[Login] → check GeneratedBooks for undownloaded PDFs
           ├─ found → show Resume Banner on HomePage → direct download
           └─ none  → show Profile Selector on HomePage
                         ├─ select existing profile → story selector → [preview]
                         │     → [FORMAT_SELECT] → [PaymentPage] → PDF saved to DB
                         └─ create new profile → name + gender + age + photo →
                               → story selector → [preview] → ...
```

### 4.3 Component Map

```
New backend files:
  backend/core/kid_profile_store.py     — KidProfile CRUD (Azure Table)
  backend/core/generated_book_store.py  — GeneratedBook CRUD (Azure Table)
  backend/routes/kid_profiles.py        — /api/v2/kids/* endpoints
  backend/routes/generated_books.py     — /api/v2/books/* endpoints

Modified backend files:
  backend/core/storage_paths.py         — add profile_photo_path()
  backend/routes/generate_async.py      — accept profile_id, save GeneratedBook
  backend/server.py                     — register two new routers

New frontend files:
  frontend/src/pages/KidProfilesPage.jsx   — create/edit/delete profiles
  frontend/src/lib/resumeCache.js          — module-level singleton for resume state

Modified frontend files:
  frontend/src/pages/HomePage.jsx          — ProfileSelector step, Resume Banner
  frontend/src/AppRoutes.jsx               — add /profiles route
```

---

## 5. Data Models

### 5.1 KidProfile

**Azure Table:** `KidProfiles`  
**PartitionKey:** `user_mobile` (e.g. `9160570733`)  
**RowKey:** `profile_id` (UUID hex, 32 chars)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `profile_id` | string | Yes | UUID hex — same as RowKey |
| `user_mobile` | string | Yes | 10-digit — same as PartitionKey |
| `name` | string | Yes | Child's first name, max 60 chars |
| `gender` | string | Yes | `"male"` \| `"female"` \| `"neutral"` |
| `age` | int | No | 0–12. Stored as int32. 0 = not set. |
| `notes` | string | No | Free text, max 200 chars |
| `photo_blob_path` | string | No | Blob path in `profiles/` prefix. Empty = no photo |
| `created_at` | string | Yes | ISO-8601 UTC |
| `updated_at` | string | Yes | ISO-8601 UTC (= created_at on creation) |

**Constraints:**
- Max 5 profiles per `user_mobile` (`MAX_KID_PROFILES_PER_USER = 5`)
- `name` minimum 1 character, maximum 60 characters
- `gender` must be one of `VALID_GENDERS` from `storage_paths.py`
- `age` must be in `[0, 12]` if provided

**JSON wire format (API responses):**
```json
{
  "profile_id": "a1b2c3d4e5f6...",
  "name":        "Niku",
  "gender":      "male",
  "age":         5,
  "notes":       "",
  "photo_url":   "/api/v2/kids/a1b2c3d4.../photo",
  "has_photo":   true,
  "created_at":  "2026-04-30T10:00:00Z",
  "updated_at":  "2026-04-30T10:00:00Z"
}
```

Note: `photo_url` is a backend-served URL, not the raw blob path. The raw
`photo_blob_path` is never exposed to the frontend.

---

### 5.2 GeneratedBook

**Azure Table:** `GeneratedBooks`  
**PartitionKey:** `user_mobile`  
**RowKey:** `book_id` (UUID hex)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `book_id` | string | Yes | UUID hex — same as RowKey |
| `user_mobile` | string | Yes | Same as PartitionKey |
| `profile_id` | string | Yes | FK → KidProfiles.profile_id |
| `story_id` | string | Yes | e.g. `forest_of_smiles` |
| `generation_id` | string | Yes | FK → GenerationSessions.generation_id |
| `child_name` | string | Yes | Snapshot of profile name at generation time |
| `pdf_blob_path` | string | No | Blob path. Empty until generation complete |
| `pdf_filename` | string | No | e.g. `niku_20260430_a1b2c3d4.pdf` |
| `status` | string | Yes | `"generating"` \| `"complete"` \| `"failed"` |
| `download_count` | int | Yes | Default 0. Incremented on each download event |
| `first_downloaded_at` | string | No | ISO-8601 UTC. Empty until first download |
| `created_at` | string | Yes | ISO-8601 UTC |
| `completed_at` | string | No | ISO-8601 UTC. Set when status → complete |

**Key constraint:** Only one active GeneratedBook per `(user_mobile, profile_id, story_id)`.
When a new generation is started for the same triple, the existing record is
**replaced** (not appended). Replacing means: update the existing record's
`generation_id`, `status`, `pdf_blob_path`, `completed_at`, reset `download_count = 0`.

**Lookup patterns needed:**
1. Find by `book_id` (direct row lookup by PK + RK)
2. Find by `(user_mobile, profile_id, story_id)` — OData filter on same partition
3. Find all `status=complete, download_count=0` for `user_mobile` — resume query
4. Find all books for a profile — OData filter

**OData filter for pattern 3 (resume):**
```
PartitionKey eq '9160570733' 
and status eq 'complete' 
and download_count eq 0
```

---

## 6. Storage Paths

### 6.1 New path function: `profile_photo_path()`

Add to `backend/core/storage_paths.py`:

```python
def profile_photo_path(user_mobile: str, profile_id: str) -> str:
    """
    Permanent blob path for a kid profile's primary photo.
    These are NOT deleted after generation — they persist for the profile lifetime.

    Format: profiles/{mobile_safe}/{profile_id}/photo.jpg

    Args:
        user_mobile: 10-digit mobile number
        profile_id:  UUID hex (32 chars)

    Returns:
        e.g. "profiles/9160570733/a1b2c3d4e5f6.../photo.jpg"
    """
    return f"profiles/{user_mobile}/{profile_id}/photo.jpg"
```

### 6.2 Updated blob layout

```
storyme-assets/
│
├── profiles/                         ← NEW — permanent profile photos
│   └── {user_mobile}/
│       └── {profile_id}/
│           └── photo.jpg             ← primary photo (always JPEG internally)
│
├── uploads/                          ← unchanged — transient (deleted after use)
├── generated/                        ← unchanged
└── pdfs/                             ← unchanged — permanent PDFs
```

---

## 7. Backend — Kid Profile Store

### 7.1 File: `backend/core/kid_profile_store.py`

Follow the exact same pattern as `backend/core/address_store.py`:
- Abstract base class with the full interface
- `AzureKidProfileStore` implementation
- Module-level `get_kid_profile_store()` factory function (lazy init, same pattern as `get_address_store()`)
- Module-level convenience functions delegating to the singleton

```python
MAX_KID_PROFILES_PER_USER = 5
_TABLE_NAME = "KidProfiles"

class KidProfileStore(ABC):
    @abstractmethod
    def list_profiles(self, user_mobile: str) -> list[dict]: ...

    @abstractmethod
    def get_profile(self, user_mobile: str, profile_id: str) -> Optional[dict]: ...

    @abstractmethod
    def upsert_profile(self, user_mobile: str, profile: dict) -> dict: ...

    @abstractmethod
    def delete_profile(self, user_mobile: str, profile_id: str) -> bool: ...

    @abstractmethod
    def count_profiles(self, user_mobile: str) -> int: ...
```

**`upsert_profile()` contract:**
- Creates if `profile_id` not found in table
- Updates if `profile_id` already exists
- Always sets `updated_at = now()`
- Returns the stored profile dict

**`delete_profile()` contract:**
- Hard-deletes the Azure Table row
- Does NOT delete the photo blob (caller handles that separately)
- Returns `True` if deleted, `False` if not found

---

## 8. Backend — Generated Book Store

### 8.1 File: `backend/core/generated_book_store.py`

Same pattern as `kid_profile_store.py`.

```python
_TABLE_NAME = "GeneratedBooks"

class GeneratedBookStore(ABC):
    @abstractmethod
    def upsert_book(self, user_mobile: str, book: dict) -> dict: ...

    @abstractmethod
    def get_book(self, user_mobile: str, book_id: str) -> Optional[dict]: ...

    @abstractmethod
    def find_book(
        self, user_mobile: str, profile_id: str, story_id: str
    ) -> Optional[dict]: ...

    @abstractmethod
    def list_pending_downloads(self, user_mobile: str) -> list[dict]: ...

    @abstractmethod
    def increment_download_count(self, user_mobile: str, book_id: str) -> bool: ...

    @abstractmethod
    def update_book_status(
        self, user_mobile: str, book_id: str, updates: dict
    ) -> bool: ...
```

**`find_book()` contract:**
- Queries by `user_mobile` (PartitionKey) + OData filter for `profile_id eq X and story_id eq Y`
- Returns the single matching record or `None`
- Returns the most recently created if duplicates exist (should not happen)

**`list_pending_downloads()` contract:**
- Returns all books for `user_mobile` where `status eq 'complete' and download_count eq 0`
- Ordered by `completed_at` descending (most recent first)
- Maximum 10 results returned (resume use case only shows the top one)

**`increment_download_count()` contract:**
- Atomically increments `download_count` by 1
- Sets `first_downloaded_at = now()` if `download_count` was 0 before
- Returns `True` on success

---

## 9. Backend — API Routes

### 9.1 Kid Profiles: `backend/routes/kid_profiles.py`

**Router prefix:** `/api/v2/kids`  
**Auth:** All endpoints require valid JWT (same as `/api/v2/user/addresses`)

#### Endpoints

---

**`GET /api/v2/kids`** — List profiles

Response:
```json
{
  "profiles": [ { ...KidProfile... } ],
  "total":    2,
  "max":      5,
  "can_add":  true
}
```

Profiles are ordered by `created_at` ascending (oldest first — consistent UX).

---

**`POST /api/v2/kids`** — Create new profile

Request: `multipart/form-data`
```
name:   string  (required, 1–60 chars)
gender: string  (required, male|female|neutral)
age:    integer (optional, 0–12)
notes:  string  (optional, max 200 chars)
photo:  file    (optional, JPEG/PNG/WEBP, max 5MB)
```

Validation:
- Return `400` if user already has `MAX_KID_PROFILES_PER_USER` profiles
- Return `400` if `gender` is not in `VALID_GENDERS`
- Return `400` if `age` is outside `[0, 12]`
- Return `400` if photo file type is not in `ALLOWED_IMAGE_TYPES`

Logic:
1. Generate `profile_id = uuid4().hex`
2. If photo provided: save to `profile_photo_path(user_mobile, profile_id)` in blob storage
3. Upsert profile record
4. Return `201` with created profile

Response:
```json
{ "profile": { ...KidProfile... }, "message": "Profile created." }
```

---

**`GET /api/v2/kids/{profile_id}`** — Get single profile

- Returns `404` if not found or belongs to a different user (same partition check)

---

**`PUT /api/v2/kids/{profile_id}`** — Update profile metadata

Request: `application/json`
```json
{
  "name":   "Niku",
  "gender": "male",
  "age":    5,
  "notes":  "Loves dinosaurs"
}
```

- Photo update is a **separate endpoint** (see below) — not included here
- Returns `404` if profile not found
- Returns `400` on validation failure
- Sets `updated_at = now()`

---

**`POST /api/v2/kids/{profile_id}/photo`** — Update profile photo

Request: `multipart/form-data` with single `photo` field.

Logic:
1. Validate file type and size
2. Upload new photo to `profile_photo_path(user_mobile, profile_id)` (overwrites existing)
3. Set `photo_blob_path` and `updated_at` on profile record
4. **Important:** Do NOT invalidate existing `GeneratedBooks` for this profile —
   old PDFs are still served correctly (they were generated with the old photo).

Response:
```json
{ "profile": { ...KidProfile... }, "message": "Photo updated." }
```

---

**`DELETE /api/v2/kids/{profile_id}`** — Delete profile

Logic:
1. Return `404` if not found
2. Hard-delete the `KidProfiles` Azure Table row
3. Delete the photo blob from storage (if `photo_blob_path` is set)
4. Do NOT delete `GeneratedBooks` records — they are retained as history
5. Do NOT delete PDF blobs — retained per A7

Response:
```json
{ "profile_id": "...", "message": "Profile deleted." }
```

---

**`GET /api/v2/kids/{profile_id}/photo`** — Serve profile photo

- Reads blob from `profile_photo_path(user_mobile, profile_id)`
- Returns `image/jpeg` response (or the stored content type)
- Returns `404` if no photo uploaded
- **Auth:** Same JWT requirement. The mobile extracted from the token must match
  the profile's owner. Users cannot access other users' photos.

This is the URL returned in `photo_url` field of the profile JSON.

---

### 9.2 Generated Books: `backend/routes/generated_books.py`

**Router prefix:** `/api/v2/books`  
**Auth:** All endpoints require valid JWT.

---

**`GET /api/v2/books/pending-downloads`** — List undownloaded completed books

Used by the home page on mount to check for the resume banner.

Response:
```json
{
  "books": [
    {
      "book_id":      "...",
      "profile_id":   "...",
      "profile_name": "Niku",
      "story_id":     "forest_of_smiles",
      "story_title":  "Niku and the Forest of Smiles",
      "completed_at": "2026-04-30T10:30:00Z",
      "download_url": "/api/v2/books/abc123.../download"
    }
  ],
  "count": 1
}
```

Only returns `status=complete, download_count=0` records.

---

**`GET /api/v2/books/{book_id}/download`** — Download the PDF

Logic:
1. Look up book by `book_id` (verify belongs to authenticated user)
2. Return `404` if not found or `status != "complete"`
3. Return `409` if `pdf_blob_path` is empty (generation failed to upload)
4. Stream/redirect to the PDF blob
5. Call `increment_download_count(user_mobile, book_id)` after successful response

The file is served as `application/pdf` with `Content-Disposition: attachment`.

---

**`POST /api/v2/books/{book_id}/downloaded`** — Explicit download acknowledgement

Called by the frontend after a successful download initiation.

Logic:
1. Verify book belongs to authenticated user
2. Call `increment_download_count()`
3. Return `{ "book_id": "...", "download_count": 1 }`

---

### 9.3 Changes to `backend/routes/generate_async.py`

Add two optional form fields to `POST /api/v2/generate/async`:

```python
@router.post("/generate/async")
async def start_async_generation(
    name:       str           = Form(...),
    image:      UploadFile    = File(None),   # Now Optional
    story_id:   str           = Form("forest_of_smiles"),
    mode:       str           = Form("opencv"),
    gender:     str           = Form("neutral"),
    profile_id: Optional[str] = Form(None),   # NEW
    # image is now optional when profile_id is provided
):
```

**Validation logic:**
```python
if profile_id:
    # Load profile from DB — use its stored photo blob path
    profile = get_kid_profile(user_mobile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    if not profile.get("photo_blob_path"):
        raise HTTPException(400, "Profile has no photo — please add one first")
    local_image_path = _resolve_local_path(profile["photo_blob_path"])
    child_name = profile["name"]   # override form name with profile name
    gender = profile["gender"]     # override form gender with profile gender
elif image:
    # Legacy flow — use uploaded image
    # (unchanged)
else:
    raise HTTPException(400, "Either profile_id or image is required")
```

**After generation completes** (in `_run_generation_task` async wrapper, after
`session_store.update_session`), create/replace the `GeneratedBook`:

```python
if profile_id and user_mobile and result.get("status") == "complete":
    book_store = get_generated_book_store()
    existing = book_store.find_book(user_mobile, profile_id, story_id)
    book = {
        "book_id":      existing["book_id"] if existing else uuid4().hex,
        "user_mobile":  user_mobile,
        "profile_id":   profile_id,
        "story_id":     story_id,
        "generation_id": gen_id,
        "child_name":   child_name,
        "pdf_blob_path": result["updates"].get("pdf_blob_path", ""),
        "pdf_filename":  result["updates"].get("pdf_filename", ""),
        "status":        "complete",
        "download_count": 0,
        "first_downloaded_at": "",
        "created_at":    existing["created_at"] if existing else now_iso,
        "completed_at":  now_iso,
    }
    book_store.upsert_book(user_mobile, book)
```

The `user_mobile` must be extracted from the JWT at the `start_async_generation`
endpoint and stored in the job tracker `_active_jobs[gen_id]` so the async
background task can access it.

---

## 10. Backend — Generation Flow Changes

### 10.1 JWT extraction in async route

Currently `generate_async.py` does not require authentication (anonymous
generation is allowed). This must remain true for backwards compatibility.

Add optional JWT extraction:

```python
from core.session_tokens import get_mobile_from_request_optional

user_mobile = get_mobile_from_request_optional(request)
# Returns None for unauthenticated requests — book record not saved
```

Add `get_mobile_from_request_optional()` to `core/session_tokens.py`:
- Same logic as `require_mobile_from_request()` but returns `None` instead of
  raising `401` when no token is present.

### 10.2 Profile photo resolution

When `profile_id` is provided, the profile photo is already in permanent blob
storage. The generation task must resolve it to a local path before passing
to `face_pipeline_service`:

```python
def _resolve_profile_photo(photo_blob_path: str) -> tuple[str, bool]:
    """
    Return (local_path, is_temp).
    For local storage: path is directly on disk.
    For Azure: download to a temp file (is_temp=True, caller must delete).
    """
    if config.STORAGE_TYPE == "local":
        return storage.get_file_path(photo_blob_path), False
    # Azure: download blob to temp file
    data   = storage.read_file(photo_blob_path)
    suffix = ".jpg"
    tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data); tmp.close()
    return tmp.name, True
```

---

## 11. Frontend — Home Page Changes

### 11.1 New step: `PROFILE_SELECT`

Insert a new step into the HomePage step machine **before** `INPUT`:

```
PROFILE_SELECT → INPUT → PREVIEWING → PREVIEW → FORMAT_SELECT
```

**`PROFILE_SELECT` renders:**
- Call `GET /api/v2/kids` on mount
- If profiles exist: show profile cards (avatar circle, name, age/gender badge)
  with a "+ Create New Profile" button
- If no profiles: show only the "+ Create New Profile" button (and a brief hint
  to create a profile to save their photo)
- "Skip / use a new photo" link at the bottom that proceeds to the old `INPUT`
  step without requiring a profile
- Clicking an existing profile card:
  1. Stores `selectedProfileId` in component state
  2. Proceeds to story selector (existing `INPUT` step but photo upload is hidden;
     name and gender are pre-filled and read-only from profile)

### 11.2 Story selector when profile is selected

The INPUT step when coming from a profile selection:
- Photo upload card is hidden (replaced by "Using Niku's saved photo" + avatar)
- `child_name` field is pre-filled and **read-only** (from profile)
- `gender` selector is pre-filled and **read-only** (from profile)
- Story, generation mode selectors remain editable

### 11.3 Resume Banner

On mount of `PROFILE_SELECT`, call `GET /api/v2/books/pending-downloads`.

If `count > 0`, show a banner **above** the profile grid:

```
┌──────────────────────────────────────────────────────────────┐
│  📚 You have an undownloaded storybook ready!                 │
│  "Niku and the Forest of Smiles" — completed 2 hours ago     │
│  [  Download Now  ]              [  Dismiss  ]               │
└──────────────────────────────────────────────────────────────┘
```

- "Download Now" calls `GET /api/v2/books/{book_id}/download` directly
  (opens in same tab with `Content-Disposition: attachment`)
- Then calls `POST /api/v2/books/{book_id}/downloaded`
- On success, hides the banner
- "Dismiss" hides the banner for the current session only
  (does not mark as downloaded)
- If multiple undownloaded books: show only the most recent one (index 0)

### 11.4 `generationCache.js` changes

When starting a generation from a profile (not ad-hoc upload), add `profile_id`
to the cache object:

```javascript
setGenCache({
  step:      STEPS.FORMAT_SELECT,
  generationId,
  profile_id: selectedProfileId || null,  // NEW
  childName, storyId, storyTitle, totalPages,
  bgGenStatus, generationMode, gender,
});
```

On cache restoration (back from PrintOrderPage), the `profile_id` is available
so the FORMAT_SELECT step can offer "Download" and the backend knows which book
to update.

---

## 12. Frontend — Resume Flow Detail

### 12.1 Sequence: logout before download

```
User generates PDF → sees FORMAT_SELECT → inactivity → logout → /

User logs in again:
  → ProtectedRoute mounts HomePage
  → PROFILE_SELECT step renders
  → GET /api/v2/books/pending-downloads → returns 1 book
  → Resume Banner shown
  → User clicks "Download Now"
  → GET /api/v2/books/{book_id}/download → browser downloads PDF
  → POST /api/v2/books/{book_id}/downloaded
  → Banner dismissed
```

### 12.2 State: No double-prompting

After the user downloads the PDF via the resume banner, `download_count` becomes 1.
On the next login, `list_pending_downloads` returns 0 books and no banner is shown.

### 12.3 State: Failed generation

If `status = "failed"`, `list_pending_downloads` does not return it (the query
filters for `status eq 'complete'`). Failed generations are silently excluded
from the resume flow.

---

## 13. No-Regression Boundary

The following are explicitly protected from change:

| Component | Protection |
|-----------|-----------|
| `POST /api/generate` | v1 sync endpoint — untouched |
| `POST /api/v2/generate/preview` | Preview endpoint — untouched |
| `POST /api/v2/generate/async` without `profile_id` | Must continue to work with image upload only |
| `GET /api/v2/generate/status/{id}` | Polling — untouched |
| `GET /api/v2/generate/download/{id}` | Existing download — untouched |
| All `print_orders.py` routes | Print ordering — untouched |
| `session_store.py` — all existing methods | GenerationSessions — untouched |
| All existing frontend pages | No layout/UX changes except HomePage new step |
| `lib/session.js` inactivity logic | Session management — untouched |
| `lib/generationCache.js` existing fields | Only `profile_id` added — backwards compatible |
| `PaymentPage`, `PrintOrderPage`, `OrderStatusPage` | Untouched |
| `AdminOrdersPage`, `AdminFaceTestPage` | Untouched |

---

## 14. Test Cases

All tests live in `backend/tests/test_kid_profiles.py`.

### 14.1 Setup

```python
# backend/tests/test_kid_profiles.py
import pytest, uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

TEST_MOBILE   = "9999000001"
TEST_MOBILE_2 = "9999000002"   # different user — for isolation tests
DUMMY_PHOTO   = Path("backend/tests/fixtures/faces/face_frontal.jpg")
```

---

### TC-KP-01: Create profile without photo

```python
def test_create_profile_no_photo():
    """Profile can be created with name and gender only — photo is optional."""
    store = get_kid_profile_store()
    profile_id = uuid.uuid4().hex
    p = store.upsert_profile(TEST_MOBILE, {
        "profile_id": profile_id,
        "user_mobile": TEST_MOBILE,
        "name": "Niku",
        "gender": "male",
        "age": 5,
        "notes": "",
        "photo_blob_path": "",
    })
    assert p["name"] == "Niku"
    assert p["photo_blob_path"] == ""
    assert p["profile_id"] == profile_id
```

---

### TC-KP-02: Create profile respects max limit

```python
def test_create_profile_max_limit():
    """Creating more than MAX_KID_PROFILES_PER_USER profiles must raise HTTP 400."""
    from httpx import AsyncClient
    import asyncio
    # POST /api/v2/kids 5 times → ok; 6th → 400
    # (integration test via TestClient or mocked route)
    count = store.count_profiles(TEST_MOBILE)
    # If already at max, upsert a 6th should fail at the route layer
    assert count <= MAX_KID_PROFILES_PER_USER
```

---

### TC-KP-03: Profile is user-isolated

```python
def test_profile_isolation():
    """User A's profiles must not be visible to User B."""
    store = get_kid_profile_store()
    pid = uuid.uuid4().hex
    store.upsert_profile(TEST_MOBILE, {
        "profile_id": pid, "user_mobile": TEST_MOBILE,
        "name": "Niku", "gender": "male",
        "age": 0, "notes": "", "photo_blob_path": "",
    })
    result = store.get_profile(TEST_MOBILE_2, pid)
    assert result is None, "Profile must not be retrievable by a different user"
```

---

### TC-KP-04: Update profile fields

```python
def test_update_profile_name():
    store = get_kid_profile_store()
    pid = uuid.uuid4().hex
    store.upsert_profile(TEST_MOBILE, {
        "profile_id": pid, "user_mobile": TEST_MOBILE,
        "name": "Niku", "gender": "male",
        "age": 5, "notes": "", "photo_blob_path": "",
    })
    updated = store.upsert_profile(TEST_MOBILE, {
        "profile_id": pid, "user_mobile": TEST_MOBILE,
        "name": "Nikita", "gender": "female",
        "age": 6, "notes": "Updated", "photo_blob_path": "",
    })
    assert updated["name"]   == "Nikita"
    assert updated["gender"] == "female"
    assert updated["age"]    == 6
```

---

### TC-KP-05: Delete profile removes from store

```python
def test_delete_profile():
    store = get_kid_profile_store()
    pid = uuid.uuid4().hex
    store.upsert_profile(TEST_MOBILE, {
        "profile_id": pid, "user_mobile": TEST_MOBILE,
        "name": "Niku", "gender": "male",
        "age": 0, "notes": "", "photo_blob_path": "",
    })
    ok = store.delete_profile(TEST_MOBILE, pid)
    assert ok is True
    assert store.get_profile(TEST_MOBILE, pid) is None
```

---

### TC-GB-01: Create generated book record

```python
def test_create_generated_book():
    store = get_generated_book_store()
    book_id = uuid.uuid4().hex
    b = store.upsert_book(TEST_MOBILE, {
        "book_id":     book_id,
        "user_mobile": TEST_MOBILE,
        "profile_id":  "profile123",
        "story_id":    "forest_of_smiles",
        "generation_id": "gen456",
        "child_name":  "Niku",
        "pdf_blob_path": "pdfs/niku/forest_of_smiles/20260430_a1b2.pdf",
        "pdf_filename":  "niku_storybook.pdf",
        "status":        "complete",
        "download_count": 0,
        "first_downloaded_at": "",
    })
    assert b["status"] == "complete"
    assert b["download_count"] == 0
```

---

### TC-GB-02: Find book by profile+story

```python
def test_find_book_by_profile_and_story():
    store = get_generated_book_store()
    book_id = uuid.uuid4().hex
    store.upsert_book(TEST_MOBILE, {
        "book_id": book_id, "user_mobile": TEST_MOBILE,
        "profile_id": "profileABC", "story_id": "forest_of_smiles",
        "generation_id": "genXYZ", "child_name": "Niku",
        "pdf_blob_path": "pdfs/...", "pdf_filename": "niku.pdf",
        "status": "complete", "download_count": 0,
        "first_downloaded_at": "",
    })
    found = store.find_book(TEST_MOBILE, "profileABC", "forest_of_smiles")
    assert found is not None
    assert found["book_id"] == book_id
    assert store.find_book(TEST_MOBILE, "profileABC", "other_story") is None
```

---

### TC-GB-03: Pending downloads query

```python
def test_list_pending_downloads():
    store = get_generated_book_store()
    bid_complete = uuid.uuid4().hex
    bid_failed   = uuid.uuid4().hex
    bid_downloaded = uuid.uuid4().hex

    for bid, status, dl in [
        (bid_complete,    "complete", 0),
        (bid_failed,      "failed",   0),
        (bid_downloaded,  "complete", 1),
    ]:
        store.upsert_book(TEST_MOBILE, {
            "book_id": bid, "user_mobile": TEST_MOBILE,
            "profile_id": f"p{bid[:4]}", "story_id": "s1",
            "generation_id": "gXX", "child_name": "Test",
            "status": status, "download_count": dl,
            "pdf_blob_path": "pdfs/...", "pdf_filename": "f.pdf",
            "first_downloaded_at": "",
        })

    pending = store.list_pending_downloads(TEST_MOBILE)
    ids = [b["book_id"] for b in pending]
    assert bid_complete in ids
    assert bid_failed       not in ids
    assert bid_downloaded   not in ids
```

---

### TC-GB-04: Download count increment

```python
def test_increment_download_count():
    store = get_generated_book_store()
    bid = uuid.uuid4().hex
    store.upsert_book(TEST_MOBILE, {
        "book_id": bid, "user_mobile": TEST_MOBILE,
        "profile_id": "pX", "story_id": "s1",
        "generation_id": "gX", "child_name": "Test",
        "status": "complete", "download_count": 0,
        "pdf_blob_path": "pdfs/...", "pdf_filename": "f.pdf",
        "first_downloaded_at": "",
    })
    ok = store.increment_download_count(TEST_MOBILE, bid)
    assert ok is True
    updated = store.get_book(TEST_MOBILE, bid)
    assert updated["download_count"] == 1
    assert updated["first_downloaded_at"] != ""

    # Second increment — count becomes 2, first_downloaded_at unchanged
    t_first = updated["first_downloaded_at"]
    store.increment_download_count(TEST_MOBILE, bid)
    again = store.get_book(TEST_MOBILE, bid)
    assert again["download_count"] == 2
    assert again["first_downloaded_at"] == t_first  # not reset on 2nd download
```

---

### TC-GB-05: Regeneration replaces book record

```python
def test_regeneration_replaces_existing_book():
    """Starting a new generation for same (profile, story) must update
    the existing book record, not create a duplicate."""
    store = get_generated_book_store()
    pid, sid = "profileA", "forest_of_smiles"

    # First generation
    bid1 = uuid.uuid4().hex
    store.upsert_book(TEST_MOBILE, {
        "book_id": bid1, "user_mobile": TEST_MOBILE,
        "profile_id": pid, "story_id": sid,
        "generation_id": "gen001", "child_name": "Niku",
        "status": "complete", "download_count": 0,
        "pdf_blob_path": "pdfs/old.pdf", "pdf_filename": "old.pdf",
        "first_downloaded_at": "",
    })

    # Second generation — same profile + story, different generation_id
    existing = store.find_book(TEST_MOBILE, pid, sid)
    assert existing is not None  # should find the first one
    store.upsert_book(TEST_MOBILE, {
        "book_id":     existing["book_id"],   # reuse same book_id
        "user_mobile": TEST_MOBILE,
        "profile_id":  pid, "story_id": sid,
        "generation_id": "gen002", "child_name": "Niku",
        "status": "complete", "download_count": 0,
        "pdf_blob_path": "pdfs/new.pdf", "pdf_filename": "new.pdf",
        "first_downloaded_at": "",
    })

    # Must still be one record
    updated = store.find_book(TEST_MOBILE, pid, sid)
    assert updated["generation_id"] == "gen002"
    assert updated["pdf_blob_path"] == "pdfs/new.pdf"
```

---

### TC-RT-01: POST /api/v2/kids creates profile

```python
@pytest.mark.asyncio
async def test_api_create_profile(test_client, authed_headers):
    resp = await test_client.post(
        "/api/v2/kids",
        data={"name": "Niku", "gender": "male", "age": "5"},
        headers=authed_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["profile"]["name"] == "Niku"
    assert body["profile"]["gender"] == "male"
    assert body["profile"]["age"] == 5
    assert "profile_id" in body["profile"]
```

---

### TC-RT-02: GET /api/v2/books/pending-downloads (empty)

```python
@pytest.mark.asyncio
async def test_api_pending_downloads_empty(test_client, authed_headers):
    resp = await test_client.get(
        "/api/v2/books/pending-downloads",
        headers=authed_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
    assert resp.json()["books"] == []
```

---

### TC-RT-03: Resume flow — generate with profile_id (no image upload)

```python
@pytest.mark.asyncio
async def test_generate_async_with_profile_id(test_client, authed_headers, profile_with_photo):
    """Starting async generation with profile_id must succeed without image upload."""
    profile_id = profile_with_photo["profile_id"]
    resp = await test_client.post(
        "/api/v2/generate/async",
        data={
            "name":       "Niku",
            "story_id":   "forest_of_smiles",
            "mode":       "opencv",
            "profile_id": profile_id,
            # No 'image' field
        },
        headers=authed_headers,
    )
    assert resp.status_code == 200
    assert "generation_id" in resp.json()
```

---

### TC-RT-04: Generate without profile_id still requires image

```python
@pytest.mark.asyncio
async def test_generate_async_no_profile_no_image(test_client, authed_headers):
    """Legacy flow: neither profile_id nor image → HTTP 400."""
    resp = await test_client.post(
        "/api/v2/generate/async",
        data={"name": "Niku", "story_id": "forest_of_smiles"},
        headers=authed_headers,
    )
    assert resp.status_code == 400
```

---

## 15. Implementation Order

Implement in this exact order:

1. **`core/storage_paths.py`** — Add `profile_photo_path()`
2. **`core/kid_profile_store.py`** — KidProfileStore + AzureKidProfileStore
3. **`core/generated_book_store.py`** — GeneratedBookStore + AzureGeneratedBookStore
4. **`core/session_tokens.py`** — Add `get_mobile_from_request_optional()`
5. **`routes/kid_profiles.py`** — All 6 KidProfile endpoints
6. **`routes/generated_books.py`** — All 3 GeneratedBook endpoints
7. **`routes/generate_async.py`** — Add `profile_id` support + book record saving
8. **`server.py`** — Register 2 new routers (defensive try/except pattern)
9. **`tests/test_kid_profiles.py`** — All TC-KP-* and TC-GB-* tests
10. **`frontend/src/pages/KidProfilesPage.jsx`** — Create/edit/delete UI
11. **`frontend/src/pages/HomePage.jsx`** — Add PROFILE_SELECT step + Resume Banner
12. **`frontend/src/AppRoutes.jsx`** — Add `/profiles` route
13. **End-to-end test** — TC-RT-01 through TC-RT-04

---

## 16. Files Modified Summary

| File | Status | Change |
|------|--------|--------|
| `backend/core/storage_paths.py` | Modified | Add `profile_photo_path()` |
| `backend/core/kid_profile_store.py` | **New** | Full kid profile CRUD |
| `backend/core/generated_book_store.py` | **New** | Generated book CRUD |
| `backend/core/session_tokens.py` | Modified | Add `get_mobile_from_request_optional()` |
| `backend/routes/kid_profiles.py` | **New** | 6 endpoints under `/api/v2/kids` |
| `backend/routes/generated_books.py` | **New** | 3 endpoints under `/api/v2/books` |
| `backend/routes/generate_async.py` | Modified | Accept `profile_id`, save GeneratedBook |
| `backend/server.py` | Modified | Register 2 new routers |
| `backend/tests/test_kid_profiles.py` | **New** | 9 test cases |
| `frontend/src/pages/KidProfilesPage.jsx` | **New** | Profile CRUD page |
| `frontend/src/pages/HomePage.jsx` | Modified | PROFILE_SELECT step + Resume Banner |
| `frontend/src/AppRoutes.jsx` | Modified | `/profiles` route |

**Files with zero changes (regression protection):**

`generate.py`, `generate_v2.py`, `generate_v3.py`, `print_orders.py`,
`auth.py`, `session_store.py`, `address_store.py`, `user_store.py`,
`PaymentPage.jsx`, `PrintOrderPage.jsx`, `OrderStatusPage.jsx`,
`AdminOrdersPage.jsx`, `AdminFaceTestPage.jsx`, `lib/session.js`,
`face_pipeline_service.py`, `pdf_service.py`, `story_json_service.py`
