# Integration Guides

Connect PDF Autofiller to automation platforms. Prefer **inspect → preview → fill**.

Auth note: production defaults require `X-API-Key`. For local try paths set `API_AUTH_ENABLED=false` or send the token header on every request.

## n8n — importable workflow

1. Start API: `API_AUTH_ENABLED=false make run-api` (or point at your host + API key)
2. In n8n: **Workflows → Import from File** → [`n8n-fill-workflow.json`](n8n-fill-workflow.json)
3. Edit **Set Profile + Base URL** if your host is not `http://localhost:8000`
4. For production, add Header Auth (`X-API-Key`) on the HTTP Request nodes
5. Execute — downloads the sample PDF, inspects fields, previews mapping, writes a filled PDF binary

### Manual HTTP Request node (copy-paste)

| Setting | Value |
|---------|-------|
| Method | `POST` |
| URL | `http://localhost:8000/fill` (or your deployed host) |
| Authentication | **Generic Credential Type → Header Auth** |
| Header Name | `X-API-Key` |
| Header Value | your `API_AUTH_TOKEN` |
| Send Body | On |
| Body Content Type | **Form-Data** / Multipart-Form-Data |

| Name | Type | Value |
|------|------|-------|
| `pdf_file` | **n8n Binary File** | `={{ $binary.data }}` |
| `user_data` | String | `={{ JSON.stringify($json.profile) }}` |
| `strict` | String | `true` |
| `flatten` | String | `false` |

Branch on error `detail.error.code` (see [API.md](../API.md#error-contract)).

## Zapier — multipart Webhooks

Use **Webhooks by Zapier → Custom Request**.

| Field | Value |
|-------|-------|
| Method | POST |
| URL | `https://your-host/fill` |
| Payload Type | **Form** |
| Headers | `X-API-Key: your-token` |

Form fields:

- `pdf_file` — file from Drive/Dropbox (**paid Zapier** usually required for reliable file parts)
- `user_data` — **one string** of JSON (Code step: `return {user_data: JSON.stringify(inputData.profile)}`)
- `strict` — `true`

### Recommended Zapier sequence

1. **Storage** downloads blank AcroForm  
2. **Webhooks** `POST /inspect` — stop if `field_count == 0` (likely a flat scan)  
3. **Webhooks** `POST /preview` — stop if `missing_required` is non-empty  
4. **Webhooks** `POST /fill` — save binary PDF  

### Common Zapier failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `415 unsupported_media_type` | PDF not a file part | Form + file field |
| `422 invalid_user_data_json` | Nested object tree | Stringify one `user_data` field |
| `401 unauthorized` | Missing key | Add `X-API-Key` |
| 0 fields written | Flat scan | Confirm with `/inspect` |

## Make.com

Same multipart pattern as n8n: HTTP module → POST → multipart → map binary PDF + JSON string + `X-API-Key`.

## LangChain / agents

```python
from langchain.tools import tool
from pdf_autofiller import fill, inspect


@tool
def fill_pdf_form(pdf_path: str, user_data: dict, output_path: str) -> str:
    """Fill a fillable PDF form from structured user data."""
    inventory = inspect(pdf_path)
    if inventory.field_count == 0:
        return "No AcroForm fields found — this PDF is probably not fillable."
    report = fill(pdf_path, user_data, output_path)
    return f"Wrote {output_path}; fields written: {len(report.written_fields)}"
```

Remote:

```python
from pdf_autofiller import PDFAutofillerClient

client = PDFAutofillerClient("https://your-service", api_key="...")
print(client.inspect("template.pdf")["field_count"])
print(client.preview("template.pdf", profile)["missing_required"])
filled, headers = client.fill("template.pdf", profile)
```
