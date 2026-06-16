# Changelog

## [unreleased] — since c2f9d23

### Authentication

- **Lazy SSO fallback.** `login()` now only performs center login. When a region API returns 401/403, the client automatically runs the SSO flow (idps → sso/login → confirmlogin → callback → whoami) to establish a full region session, then retries. On deployments that don't support SSO, the failure is logged once and `_sso_completed` is set to prevent further retries.
- **Separate center / region tokens.** Center login produces `_center_token`; on SSO success, `whoami` provides `_region_token`. Region API calls prefer `_region_token` when available.
- **Session cookie support.** All requests now go through `requests.Session`, persisting cookies (e.g. `zitadel.access-token`, `cloud-server.id-token`) across requests.

### Debug logging

- Every request logs `method`, `url`, `kwargs`, and full headers.
- Non-2xx responses log the response body (first 500 chars).

### Configuration

- `main.py` reads `TACNODE_ENDPOINT`, `TACNODE_REGION_ENDPOINT`, `TACNODE_USERNAME`, `TACNODE_PASSWORD` from environment.

### Dependencies

- Added `pydantic>=2.0`.

### Models (`models.py`)

- `Nodegroup` — full nodegroup details with nested `NodegroupConditions` and `AutoPauseConfig`.
- `NodegroupList` — paginated list wrapper.
- `Catalog`, `CatalogGeneration`, `CatalogList` — catalog models.
- All models use `alias_generator=to_camel` with `populate_by_name=True` for automatic camelCase ↔ snake_case mapping.

### New APIs

| Method | Description |
|---|---|
| `list_nodegroups(lake_id, page_num, page_size) -> NodegroupList` | List nodegroups with pagination. |
| `get_nodegroup(lake_id, instance_id) -> Nodegroup` | Get single nodegroup details. |
| `resume_nodegroup(lake_id, instance_id, blocking=True)` | Resume a PAUSED nodegroup. Blocks until RUNNING (max 15 min). Skips if already RUNNING. |
| `pause_nodegroup(lake_id, instance_id, blocking=True)` | Pause a RUNNING nodegroup. Blocks until PAUSED (max 15 min). |
| `resize_nodegroup(lake_id, instance_id, target_size, blocking=True)` | Resize a RUNNING nodegroup. Blocks until size reached (max 15 min). |
| `list_catalogs(lake_id) -> CatalogList` | List catalogs for a context lake. |
| `create_nodegroup(lake_id, name, catalog_name, target_size, auto_pause)` | Create a nodegroup. Automatically checks catalog existence and passes ID or name accordingly. |

### Behavior changes

- **Pre-condition checks.** `resume_nodegroup` requires PAUSED, `pause_nodegroup` requires RUNNING, `resize_nodegroup` requires RUNNING. Violations raise `RuntimeError`.
- **Blocking defaults to `True`.** All state-changing methods (`resume`, `pause`, `resize`) now block by default and return a `Nodegroup` model when complete. Set `blocking=False` for fire-and-forget (returns `None`).
- **State-change APIs return `None`** in non-blocking mode since the server responds with `200` + empty body.
