# Integration Guides

Connect PDF Autofiller to automation platforms and AI agent workflows.

Auth note: production defaults require `X-API-Key`. For local try paths set `API_AUTH_ENABLED=false` or send the token header on every request.

## n8n — HTTP Request (copy-paste)

Use the **HTTP Request** node to call `POST /fill` (or `/preview` / `/inspect`) with multipart form data.

### Node configuration

| Setting | Value |
|---------|-------|
| Method | `POST` |
| URL | `http://localhost:8000/fill` (or your deployed host) |
| Authentication | **Generic Credential Type → Header Auth** |
| Header Name | `X-API-Key` |
| Header Value | your `API_AUTH_TOKEN` |
| Send Body | On |
| Body Content Type | **Form-Data** / Multipart-Form-Data |
| Specify Body | Using Fields Below |

### Body fields

| Name | Type | Value |
|------|------|-------|
| `pdf_file` | **n8n Binary File** | Expression: `={{ $binary.data }}` (or the binary property from Drive/Dropbox) |
| `user_data` | String | `={{ JSON.stringify($json.profile) }}` — must be a **JSON object string**, not nested form fields |
| `strict` | String | `true` |
| `allow_fallback_mapping` | String | `false` |
| `use_semantic_inference` | String | `false` |
| `flatten` | String | `false` (set `true` for archival non-editable PDFs) |

### Response handling

- Success: binary PDF. Save with a **Write Binary File** or Drive upload node.
- Read headers `X-PDF-Fields-Written`, `X-PDF-Fields-Skipped-Review`, `X-PDF-Fields-Skipped-Empty`.
- Errors: JSON `{ "detail": { "error": { "code", "message", "details" } } }` — branch on `code`.

### Optional: preview before fill

Duplicate the node, change URL to `/preview`, and parse the JSON `decisions` / `missing_required` / `unmapped_user_keys` before calling `/fill`.

### Example workflow

1. **Webhook** receives `{ "profile": { "firstname": "Jane", ... } }`
2. **Google Drive** downloads the blank PDF template (binary)
3. **HTTP Request** fills via `/fill` (multipart as above)
4. **Google Drive** uploads the filled PDF binary

## Zapier — multipart caveats

Use **Webhooks by Zapier → Custom Request**.

| Field | Value |
|-------|-------|
| Method | POST |
| URL | `https://your-host/fill` |
| Data Pass-Through | No |
| Unflatten | No |
| Payload Type | **Form** (not JSON) |

Form fields:

- `pdf_file` — file from a prior Drive/Dropbox step (**Zapier paid plans** are typically required for reliable file upload in Webhooks)
- `user_data` — a **single string** containing JSON (use Formatter → Utilities → Line-item to JSON, or a Code step). Do **not** split profile keys into separate form fields — the API expects one `user_data` text field.
- `strict` — `true`
- Optional: `flatten` — `true` / `false`

Headers:

```text
X-API-Key: your-token
```

### Common Zapier failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `415 unsupported_media_type` | PDF not sent as a file part | Use Form payload + file field, not base64 in JSON body |
| `422 invalid_user_data_json` | `user_data` is an object tree Zapier nested | Stringify to one field |
| `401 unauthorized` | Missing/wrong key | Add `X-API-Key` header; match `API_KEY_HEADER` |
| Empty PDF / 0 fields written | Flat scan, not AcroForm | Confirm with `/inspect` first |

**Tip:** If your Zap cannot attach files as multipart, base64-encode in a Code step and use a thin proxy that decodes to `/fill` (see below). Prefer native multipart when possible.

## LangChain / AI agents

Expose PDF filling as a tool in your agent:

```python
from langchain.tools import tool
from pdf_autofiller import fill


@tool
def fill_pdf_form(pdf_path: str, user_data: dict, output_path: str) -> str:
    """Fill a fillable PDF form from structured user data."""
    report = fill(pdf_path, user_data, output_path)
    return f"Filled PDF written to {output_path}. Fields written: {len(report.written_fields)}"
```

For remote API usage:

```python
from pdf_autofiller.client import PDFAutofillerClient

client = PDFAutofillerClient("https://your-service.onrender.com", api_key="...")
filled, headers = client.fill("template.pdf", profile_dict)
```

## Make.com (Integromat)

Same pattern as n8n:

1. **HTTP → Make a request**
2. Method POST, multipart body
3. Map binary PDF + JSON profile string from prior modules
4. Header `X-API-Key`

## Webhook middleware pattern

If your automation tool can't send multipart file uploads directly, add a thin proxy:

```
POST /your-proxy/fill
{ "pdf_base64": "...", "user_data": { ... } }
```

Decode base64 server-side and forward to `/fill`. This repo ships `/fill` natively — prefer direct multipart when your platform supports it.
