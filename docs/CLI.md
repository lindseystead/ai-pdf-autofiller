# Command Line Reference

Every command runs the pipeline in-process. There is no server to start and no
token to configure for local use.

```bash
pip install pdf-autofiller
pdf-autofiller --help
```

Add `--json` before any subcommand to get machine-readable output instead of the
human summary — useful in scripts and CI.

---

## The usual loop

Working with a form you have not seen before goes like this:

```bash
pdf-autofiller init form.pdf > me.json                          # 1. get a data file
$EDITOR me.json                                                # 2. fill it in
pdf-autofiller inspect form.pdf --data me.json                 # 3. check first
pdf-autofiller fill form.pdf --data me.json --out filled.pdf   # 4. produce it
```

Steps 1 and 3 write nothing. You never have to guess a key name or read an error
to find out what a form wants.

---

## `inspect`

List a form's fields and preview exactly what a fill would do. **Writes nothing.**

```bash
pdf-autofiller inspect form.pdf --data me.json
```

```
form.pdf: 5 fields, 1 pages
fingerprint: 922efc3ca405cfeb28d29c644deff70a

 + txtFirstName  text      first_name [required] -> 'Jane'
 ! txtLastName   text      last_name [required]
   txtEmail      text      email_address

would write 1, would skip 1
missing required: txtLastName
legend: + will fill   ? needs review   ! required and unmapped
```

| Marker | Meaning |
|--------|---------|
| `+` | This field will be filled |
| `?` | Mapped, but the value looked ambiguous — flagged for review and skipped |
| `!` | Required, and nothing in your data matched it |
| (blank) | Optional and unmapped |

The `fingerprint` identifies the form's field structure. It is stable across
re-downloads of the same document, and is what a template is keyed by.

---

## `fill`

Fill a form and write the result.

```bash
pdf-autofiller fill form.pdf --data me.json --out filled.pdf
```

| Option | Effect |
|--------|--------|
| `--out PATH` | Output path (default: `<input>_filled.pdf`) |
| `--flatten` | Remove the interactive form so the result cannot be edited |
| `--no-key-reuse` | Use each data key for at most one field |
| `--overrides FILE` | JSON of `field_name -> value` that wins over any matching |
| `--infer` | Use a model provider to infer what opaque field names mean |
| `--allow-fallback` | Let the provider resolve fields deterministic matching missed |

Use `--flatten` for anything leaving your organization: it stamps the values into
the page and strips the form, so a recipient cannot alter what you sent.

Fill refuses to produce a document when a required field is unresolved, because a
form that looks complete but is not is worse than no form at all.

---

---

---

## `init`

Emit a starter data file carrying the keys this form actually wants.

```bash
pdf-autofiller init form.pdf > me.json
```

```json
{
  "first_name": "",
  "last_name": "",
  "date_of_birth": "",
  "email_address": ""
}
```

Required fields come first, so the keys you must supply are at the top of the
file. `--annotate` adds a `_fields` block describing which PDF field each key
feeds, whether it is required, and any permitted values:

```json
{
  "_fields": {
    "first_name": { "fields": ["txtFirstName"], "required": true, "type": "text", "options": [] }
  },
  "first_name": ""
}
```

JSON has no comments, so the annotations travel as data. Keys beginning with an
underscore are ignored when the file is used as input, so an annotated skeleton
can be filled in and passed straight to `fill` without stripping anything.

---

## `extract`

Read the values back out of a PDF that is already filled.

```bash
pdf-autofiller extract filled.pdf
```

```json
{
  "first_name": "Jane",
  "last_name": "Doe"
}
```

Keys are semantic meanings by default, which is the shape `--data` and profiles
expect, so the output round-trips straight back into a fill. `--raw` keys by
exact PDF field name instead — the shape `--overrides` expects.

Empty fields are omitted: a blank field means "not answered", and carrying it
forward as `""` would later overwrite a real value with nothing. `--include-empty`
keeps them.

```bash
pdf-autofiller extract filled.pdf --save-profile jane
```

Turns a form someone completed by hand into a reusable profile in one step.

A flattened or scanned PDF has no form fields to read, so `extract` reports
`pdf_no_form_fields` rather than returning an empty result — and refuses to save
an empty profile.

---

## `validate`

Check that a PDF is a fillable AcroForm this tool can handle. Exits non-zero if
it is not.

```bash
pdf-autofiller validate form.pdf
```

Useful as a guard in scripts before a batch run. Named errors are reported for
encrypted documents, XFA forms, and files with no fillable fields.

---

## `batch`

Fill one form once per row of data.

```bash
pdf-autofiller batch onboarding.pdf --csv staff.csv --out-dir ./packets
pdf-autofiller batch onboarding.pdf --items rows.json --out-dir ./packets
```

With `--csv`, each column header is a data key and each row is one document. A
`name` column, if present, names the output file; otherwise rows are numbered.
Empty cells are treated as "not supplied" rather than "set this to empty", so a
sparse spreadsheet does not blank out values coming from a profile.

```csv
name,firstname,lastname,dob
alice,Alice,Ng,1988-02-03
bob,Bob,Ray,1991-07-09
```

With `--items`, the file is a JSON array of `{"name": ..., "user_data": {...}}`.
Exactly one of the two is required.

A row that fails is reported and skipped; the rest of the batch still runs. The
exit code is non-zero if any row failed, so CI notices.

---

## `profile`

Named, reusable sets of data.

```bash
pdf-autofiller profile set me --data me.json
pdf-autofiller profile list
pdf-autofiller profile show me
pdf-autofiller profile delete me
pdf-autofiller fill form.pdf --profile me
```

Profiles are JSON files under `~/.pdf-autofiller/profiles` (override with
`PDF_AUTOFILLER_STATE_DIR`). They are plain files on purpose: inspectable,
diffable, and yours to back up or check into a private repo.

---

## `template`

Remembered settings for one form.

```bash
pdf-autofiller template save w9 w9.pdf --flatten
pdf-autofiller template list
pdf-autofiller fill w9.pdf --profile me --template w9
```

A template stores the form's fingerprint, any field overrides, and whether to
flatten. Combine with a profile and a recurring fill becomes one command.

---

## Nested data

Data does not have to be flat. Both of these fill an email field:

```json
{ "email": "jane@example.com" }
{ "contact": { "email": "jane@example.com" } }
```

Nested values are matched on both the leaf (`email`) and the full path
(`contact.email`), so data coming straight out of a CRM or HR system works
without reshaping it first.

---

## Precedence

When several sources supply a value, most specific wins:

```
profile  <  --data / --set  <  template overrides  <  --overrides
```

A profile is a default you can always correct in the moment; an override is the
final word.

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Completed with failures (a batch row failed, or `validate` rejected the file) |
| `2` | The command could not run (bad input, unreadable PDF, unresolved required field) |
