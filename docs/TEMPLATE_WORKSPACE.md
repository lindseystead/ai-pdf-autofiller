# Durable template workspace

The `/v1` API turns the stateless PDF engine into a repeatable reviewed workflow. It stores blank
PDFs, mappings, immutable published versions, value-free job reports, and generated artifacts. Raw
fill payloads are processed in memory and are not written to the metadata database.

## Lifecycle

1. `POST /v1/templates` with `name` and `pdf_file` creates version 1 as a draft. An optional
   `field_mapping` JSON form value preserves an already-reviewed mapping from the playground.
2. Review or change the exact field mapping in the playground or with
   `PUT /v1/templates/{id}/mapping`. Supply the current `expected_revision`; stale saves return
   `409 template_revision_conflict` instead of overwriting another review.
3. `POST /v1/templates/{id}/publish` validates every required field and freezes the version.
4. `POST /v1/templates/{id}/fills` accepts JSON data and always uses the latest published version.
5. Fetch the value-free job report from `GET /v1/jobs/{job_id}` and the completed PDF from its
   authenticated `artifact_url`.
6. `POST /v1/templates/{id}/versions` uploads a replacement PDF as the next draft. Production fills
   continue using the last published version until the new draft is reviewed and published.

`GET /v1/templates/{id}/corrections` exports the mapping changes made during review. Records contain
only the field name, previous key, approved key, version, and timestamp—never form values. Use this
as evaluation evidence or to propose deterministic aliases; do not automatically promote a single
customer correction into a global alias.

Every `/v1` route is authenticated and rate limited. The browser playground sends the API key from
its existing API-key field. Published mappings are deterministic; stored fills never enable AI.

## Storage and privacy

`PRODUCT_DATA_DIR` contains:

```text
metadata.sqlite3
objects/
  sources/<sha256>.pdf
  artifacts/<job-id>.pdf
```

Source objects are content-addressed and written atomically. Artifact keys are UUIDs and path
traversal is rejected. Metadata uses transactions, foreign keys, a single-draft invariant, and
optimistic mapping revisions. Files and directories are created with private permissions where the
operating system permits it.

The application does **not** delete completed artifacts automatically. Operators must define a
retention policy appropriate to their data classification. Encrypt the volume, restrict filesystem
access, back it up if required, and delete expired artifacts outside the application until a
retention worker is configured.

## Deployment boundary

The included adapter is designed for a single self-hosted deployment on one persistent volume. It
does not provide user accounts, tenant isolation, distributed locking, regional replication, or
horizontal writes. The current `API_AUTH_TOKEN` protects the whole deployment.

Before offering a multi-tenant managed service, implement the same repository/object-store boundary
using PostgreSQL and S3-compatible object storage, add workspace-scoped credentials, and move fill
execution to a durable worker queue. Do not put SQLite on a shared network filesystem and run
multiple writers.

## Minimal API example

```bash
curl -H 'X-API-Key: ...' \
  -F 'name=Client intake' \
  -F 'pdf_file=@intake.pdf;type=application/pdf' \
  http://localhost:8000/v1/templates

curl -H 'X-API-Key: ...' -H 'Content-Type: application/json' \
  -d '{"expected_revision":1}' \
  http://localhost:8000/v1/templates/TEMPLATE_ID/publish

curl -H 'X-API-Key: ...' -H 'Content-Type: application/json' \
  -d '{"data":{"first_name":"Jane","last_name":"Doe"}}' \
  http://localhost:8000/v1/templates/TEMPLATE_ID/fills
```
