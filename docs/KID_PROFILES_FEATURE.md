# StoryMe — Kid Profiles & PDF Persistence

**Feature:** SPEC-003  
**Status:** Implemented  
**Branch:** `beta`

---

## What This Feature Does

Before this feature, every time a user wanted to generate a storybook they had
to re-upload their child's photo and re-enter the name. If the session timed out
(10 minutes of inactivity) before they downloaded the PDF, the generated file
was permanently lost.

This feature solves both problems:

1. **Kid Profiles** — Save your child's photo once. Select their profile on
   every subsequent visit — no re-upload required.

2. **PDF Persistence** — Generated PDFs are stored permanently per profile.
   If you log out before downloading, the next time you log in you'll see a
   "Resume Download" banner with a direct link.

---

## User Flows

### Flow A — First-time user (no profiles)

```
Login
  │
  ▼
Home Page — PROFILE_SELECT step
  │  No profiles found
  │
  ├── Click "+ New Profile" ────────────────────────────────────────►
  │                                                            /profiles page
  │                                                            Enter name, gender,
  │                                                            age, upload photo
  │                                                            ◄────────────────
  │  Profile created → back to Home
  │
  └── Click "Skip — use a one-time photo" ──────────────────────────►
         (legacy flow — no profile saved)
         Upload photo + name → Preview → Format Select → Download/Email/Print
```

### Flow B — Returning user with profile

```
Login
  │
  ▼
Home Page — PROFILE_SELECT step
  │  Shows profile grid (avatar, name, age)
  │
  ▼
Select "Niku" ────────────────────────────────────────────────────────►
  │                                                           INPUT step
  │                                                           ✓ Name pre-filled (read-only)
  │                                                           ✓ Photo shown (no upload)
  │                                                           Choose story + options
  │                                                           ◄─────────────────────
  ▼
Click "Generate Preview" ──────────────────────────────────────────────►
  │                                                           PREVIEWING step
  │                                                           POST /api/v2/generate/preview
  │                                                           (same as before)
  │                                                           ◄─────────────────────
  ▼
PREVIEW step — "Continue to Options" ──────────────────────────────────►
  │                                                           FORMAT_SELECT
  │                                                           POST /api/v2/generate/async
  │                                                           ← passes profile_id
  │                                                           ← NO image upload
  │                                                           Background generation starts
  │                                                           GeneratedBook created in DB
  │                                                           ◄─────────────────────
  ▼
Choose Download / Email / Print
  │
  ▼
PaymentPage → Download PDF
```

### Flow C — User logs out before downloading

```
Login
  │
  ▼
Home Page — PROFILE_SELECT step
  │
  │  GET /api/v2/books/pending-downloads → returns 1 book
  │
  ▼
┌────────────────────────────────────────────────────────────────┐
│  📚  Your storybook is ready to download!                      │
│  "Niku and the Forest of Smiles" — completed 2 hours ago       │
│  [ Download Now ]                            [ Dismiss ]       │
└────────────────────────────────────────────────────────────────┘
  │
  ├── "Download Now" ──────────────────────────────────────────────►
  │                                        GET /api/v2/books/{id}/download
  │                                        PDF streamed to browser
  │                                        download_count → 1
  │                                        Banner hidden
  │
  └── "Dismiss" ──────────────────────────────────────────────────►
                                           Banner hidden for this session
                                           download_count stays 0
                                           (banner will reappear on next login)
```

### Flow D — Managing profiles

```
Home Page (any step)
  │
  ├── Click "Manage" (top-right of profile grid) ──────────────────►
  │                                                        /profiles page
  │
  └── Click profile Edit (pencil icon) ───────────────────────────►
                                                           Edit form:
                                                           • Name
                                                           • Gender (Male/Female/Neutral)
                                                           • Age (0–12, optional)
                                                           • Notes (optional)
                                                           • Replace photo
                                                           Save → profile updated
```

---

## Architecture

### New Azure Tables

```
Azure Table Storage
│
├── KidProfiles          (NEW)
│   PartitionKey = user_mobile
│   RowKey       = profile_id (UUID hex)
│   Fields:
│     name, gender, age, notes
│     photo_blob_path    ← permanent blob path
│     created_at, updated_at
│
└── GeneratedBooks       (NEW)
    PartitionKey = user_mobile
    RowKey       = book_id (UUID hex)
    Fields:
      profile_id, story_id, generation_id
      child_name, pdf_blob_path, pdf_filename
      status:  generating | complete | failed
      download_count  (0 = never downloaded)
      first_downloaded_at, created_at, completed_at
```

### New Blob Storage Prefix

```
storyme-assets/
│
├── profiles/                ← NEW (permanent — never auto-deleted)
│   └── {user_mobile}/
│       └── {profile_id}/
│           └── photo.jpg
│
├── uploads/                 ← unchanged (transient — deleted after use)
├── generated/               ← unchanged
└── pdfs/                    ← unchanged (permanent PDFs)
```

### New API Endpoints

```
Kid Profiles (/api/v2/kids)
──────────────────────────
GET    /api/v2/kids                     List all profiles for user
POST   /api/v2/kids                     Create profile (multipart)
GET    /api/v2/kids/{profile_id}        Get single profile
PUT    /api/v2/kids/{profile_id}        Update name/gender/age/notes
POST   /api/v2/kids/{profile_id}/photo  Replace profile photo
DELETE /api/v2/kids/{profile_id}        Delete profile + photo blob
GET    /api/v2/kids/{profile_id}/photo  Serve profile photo (auth-gated)

Generated Books (/api/v2/books)
────────────────────────────────
GET  /api/v2/books/pending-downloads    Undownloaded completed books (resume banner)
GET  /api/v2/books/{book_id}/download   Download PDF + increment counter
POST /api/v2/books/{book_id}/downloaded Explicit download acknowledgement

Modified
────────
POST /api/v2/generate/async             Now accepts optional profile_id field
                                        When profile_id given: uses stored photo,
                                        saves GeneratedBook record on completion
```

---

## Data Model Reference

### KidProfile

| Field | Type | Description |
|-------|------|-------------|
| `profile_id` | string (UUID) | Unique identifier |
| `user_mobile` | string | Owner's mobile number |
| `name` | string | Child's first name (1–60 chars) |
| `gender` | string | `male` \| `female` \| `neutral` |
| `age` | integer | Child's age in years (0–12; 0 = not set) |
| `notes` | string | Optional free text (max 200 chars) |
| `photo_blob_path` | string | Blob path to stored photo |
| `created_at` | ISO string | Creation timestamp |
| `updated_at` | ISO string | Last update timestamp |

**API response includes:** `photo_url` (backend-served URL) and `has_photo` (boolean).  
`photo_blob_path` is **never** returned to the frontend.

**Limits:**
- Maximum **5 profiles** per user account
- Photo: JPEG / PNG / WEBP, maximum 5 MB

### GeneratedBook

| Field | Type | Description |
|-------|------|-------------|
| `book_id` | string (UUID) | Unique identifier |
| `user_mobile` | string | Owner |
| `profile_id` | string | FK → KidProfiles |
| `story_id` | string | e.g. `forest_of_smiles` |
| `generation_id` | string | FK → GenerationSessions |
| `child_name` | string | Snapshot of name at generation time |
| `pdf_blob_path` | string | Permanent PDF location |
| `pdf_filename` | string | e.g. `niku_20260501_a1b2c3d4.pdf` |
| `status` | string | `generating` \| `complete` \| `failed` |
| `download_count` | integer | Incremented on each download |
| `first_downloaded_at` | ISO string | First download timestamp (empty if never) |
| `completed_at` | ISO string | When generation completed |

**Key rule:** One GeneratedBook per `(user, profile, story)`. Re-generating
replaces the existing record (same `book_id`, new `generation_id`, reset `download_count`).

---

## File Reference

### New Files

| File | Purpose |
|------|---------|
| `backend/core/kid_profile_store.py` | KidProfile CRUD — Azure Table + JSON fallback |
| `backend/core/generated_book_store.py` | GeneratedBook CRUD — Azure Table + JSON fallback |
| `backend/routes/kid_profiles.py` | `/api/v2/kids/*` endpoints |
| `backend/routes/generated_books.py` | `/api/v2/books/*` endpoints |
| `frontend/src/pages/KidProfilesPage.jsx` | Profile management UI at `/profiles` |
| `backend/tests/test_kid_profiles.py` | Test cases (see SPEC-003) |

### Modified Files

| File | Change |
|------|--------|
| `backend/core/storage_paths.py` | Added `profile_photo_path()` |
| `backend/routes/generate_async.py` | Added `profile_id` + `Request` params; saves `GeneratedBook` on completion |
| `backend/server.py` | Registered `kid_profiles_router` and `generated_books_router` |
| `frontend/src/pages/HomePage.jsx` | Added `PROFILE_SELECT` step + Resume Banner |
| `frontend/src/AppRoutes.jsx` | Added `/profiles` route |

---

## Environment Variables

No new environment variables required. The feature uses the existing:
- `AZURE_STORAGE_CONNECTION_STRING` — for both new Azure Tables and blob storage
- Session JWT (from `SESSION_SECRET_KEY`) — for auth on all new endpoints

---

## Local Development

In local development, `AZURE_STORAGE_CONNECTION_STRING` is not set.
Both stores automatically fall back to JSON files:

```
backend/data/kid_profiles.json       ← KidProfile records
backend/data/generated_books.json    ← GeneratedBook records
```

Profile photos are stored in:
```
backend/uploads/profiles/{mobile}/{profile_id}/photo.jpg
```
(resolved via the existing `LocalStorage.get_file_path()` mechanism)

---

## No-Regression Notes

The following were explicitly not changed:
- `POST /api/generate` (v1 sync) — unchanged
- `POST /api/v2/generate/preview` — unchanged  
- `POST /api/v2/generate/async` **without** `profile_id` — unchanged (image upload still works)
- All `print_orders.py` routes — unchanged
- `PaymentPage`, `PrintOrderPage`, `OrderStatusPage` — unchanged
- `lib/session.js` inactivity timer — unchanged

---

## Assumptions (documented)

See `docs/specs/SPEC-003-kid-profiles-and-pdf-persistence.md` §2 for the full
list of 11 assumptions. Key ones:

- **A1:** One primary photo per profile (no multi-photo in this iteration)
- **A2:** Updating profile photo does NOT invalidate old generated PDFs
- **A3:** One GeneratedBook per `(profile, story)` — regeneration replaces it
- **A6:** Max 5 profiles per user (configurable via `MAX_KID_PROFILES_PER_USER`)
- **A7:** Profile deletion retains PDF blobs for 30 days
