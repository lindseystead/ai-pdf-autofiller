# Integration Guides

Connect PDF Autofiller to automation platforms and AI agent workflows.

## n8n

Use the **HTTP Request** node to call `POST /fill` with multipart form data.

### Node configuration

| Setting | Value |
|---------|-------|
| Method | POST |
| URL | `https://your-service.onrender.com/fill` |
| Authentication | Header Auth → `X-API-Key` |
| Body content type | Multipart Form-Data |

### Body fields

| Name | Type | Value |
|------|------|-------|
| `pdf_file` | Binary | PDF from previous node (e.g. Google Drive download) |
| `user_data` | String | `{{ JSON.stringify($json.profile) }}` |
| `strict` | String | `true` |

### Example workflow

1. **Webhook** receives `{ "profile": { "firstname": "Jane", ... } }`
2. **Google Drive** downloads the blank PDF template
3. **HTTP Request** fills the PDF via `/fill`
4. **Google Drive** uploads the filled PDF

Import starter workflow JSON: save the curl from [recipes/sample-form.sh](../../recipes/sample-form.sh) as an HTTP Request node and wire profile JSON from the trigger.

## Zapier

Use **Webhooks by Zapier → Custom Request**.

| Field | Value |
|-------|-------|
| Method | POST |
| URL | `https://your-service.onrender.com/fill` |
| Data pass-through | No |
| Payload type | Form Data |

Add fields:
- `pdf_file` — file from Google Drive / Dropbox step (requires Zapier paid plan for file upload)
- `user_data` — JSON string from Formatter or previous Zap step
- `strict` — `true`

Headers: `X-API-Key: your-token`

**Tip:** For file uploads in Zapier, use a Code step to base64-encode the PDF and a small middleware, or host the playground on Render and call from a custom integration.

## LangChain / AI agents

Expose PDF filling as a tool in your agent:

```python
from langchain.tools import tool
from pdf_autofiller import fill


@tool
def fill_pdf_form(pdf_path: str, user_data: dict, output_path: str) -> str:
    """Fill a fillable PDF form from structured user data."""
    headers = fill(pdf_path, user_data, output_path)
    written = headers.get("x-pdf-fields-written", headers.get("X-PDF-Fields-Written", "?"))
    return f"Filled PDF written to {output_path}. Fields written: {written}"
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
3. Map binary PDF + JSON profile from prior modules

## Webhook middleware pattern

If your automation tool can't send multipart file uploads directly, add a thin proxy:

```
POST /your-proxy/fill
{ "pdf_base64": "...", "user_data": { ... } }
```

Decode base64 server-side and forward to `/fill`. This repo ships `/fill` natively — prefer direct multipart when your platform supports it.
