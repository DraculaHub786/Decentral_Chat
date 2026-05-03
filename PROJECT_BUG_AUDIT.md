# Decentral_Chat Bug Audit (Retested After Fixes)

This audit reflects the latest code state after applying fixes and rerunning checks.

## Retest evidence

- Frontend signature retest:
  - `searchResults` duplicate removed (`searchResults` now only at line ~5141; Add Contact uses `addContactSearchResults`).
  - Bad block endpoint removed (`/contacts/${activeChat.other_user_id}/block` no longer present).
  - `/users/block` with JSON body is present.
  - Duplicate init blocks removed (emoji-init duplicate and responsive-init duplicate not present).
- Backend checks:
  - `python -m pip install -r backend/requirements.txt` completed.
  - `python -c "import server"` => `SERVER_IMPORT_OK`
  - `python backend/test_converter.py` => completed successfully.

## Status by issue

| ID | Previous issue | Current status | What was changed |
|---|---|---|---|
| F1 | Mobile null dereference on missing `debugFileBtn` | **FIXED** | Added null guard before style access in mobile debug block. |
| F2 | `callInfo` selector mismatch | **FIXED** | `id="callInfo"` is present in call overlay and JS reference is valid. |
| F3 | Duplicate `id="searchResults"` across modals | **FIXED** | Add Contact container renamed to `addContactSearchResults`; related JS updated. |
| F4 | `countDisplay` undefined in add-members UI | **FIXED** | `countDisplay` declaration added and used correctly. |
| F5 | Duplicate selected-count IDs | **FIXED** | Split into `forwardSelectedCountText` and `groupSelectedCountText`. |
| F6 | Wrong block endpoint (`/contacts/{id}/block`) | **FIXED** | Updated to `POST /users/block` with `{ user_id }` payload. |
| D1 | Duplicate emoji init DOMContentLoaded block | **FIXED** | Removed duplicate block; main init path retained. |
| D2 | Duplicate responsive init DOMContentLoaded block | **FIXED** | Removed duplicate block; main init path retained. |
| B1 | Frontend/backend block API contract drift | **FIXED** | Frontend aligned to backend `/api/users/block` + `/api/users/unblock` model. |
| B2 | Firestore `update()` on possibly missing user doc | **FIXED** | Replaced affected user-doc writes with `set(..., merge=True)` in profile/settings/phone/avatar/email/sync paths. |
| B3 | Missing backend dependency manifest | **FIXED** | Added `backend/requirements.txt` and installed dependencies. |
| B4 | Sensitive startup secret fragments in logs | **FIXED** | Removed secret-fragment logging; startup now logs only safe configuration status. |

## Remaining note

- `backend/server_error.log` still contains old historical errors (from before these changes).  
  These are log history entries, not proof of current failure after the applied fixes.

