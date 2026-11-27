# Privacy-safe product telemetry

Telemetry is **off by default**. Set `PRODUCT_TELEMETRY_ENABLED=true` to emit aggregate product
events to the normal application log under `pdf_autofiller.product`.

Events contain only counts and feature flags: fields inspected, mapping decisions, unresolved
required fields, records written or failed, dry-run status, and whether either optional AI path
was enabled. The emitter rejects unapproved dimensions, so routes cannot accidentally add PDF
field names, filenames, user-data keys or values, IP addresses, or request identifiers.

No event is sent to PDF Autofiller's maintainers or another service. A self-hosted operator may
route its own logs to its existing observability system and apply its normal retention policy.

Useful pilot measures:

- successful fills / fill attempts;
- templates followed by previews and fills;
- missing-required rate;
- batch failure rate;
- AI-enabled rate compared with deterministic-only success.

These events intentionally do not identify a user or template. Measuring weekly retention needs
an operator-owned account/workspace identifier outside this library, with appropriate consent and
privacy review.
