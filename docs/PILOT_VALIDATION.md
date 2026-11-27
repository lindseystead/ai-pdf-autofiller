# Design-partner pilot

The initial wedge is teams that repeatedly fill existing AcroForms from structured data and need
self-hosting or strong data residency. Do not recruit one-off consumer PDF users or promise scanned
PDF, XFA, OCR, or e-signature support.

## Participant criteria

Recruit 3–5 teams that each process at least 50 repeated forms per month and can provide an
operator-owned or licensed blank template with synthetic data. Useful starting segments are
nonprofit/government operations, HR onboarding, regulated intake, and case management.

No outreach is automated by this repository. A maintainer must approve participants,
communications, consent language, and data-handling terms.

## Pilot workflow

1. Record the current process, monthly volume, failure cost, and time per completed form.
2. Confirm the blank PDF is an unlocked AcroForm and may be used for testing.
3. Ask the participant to upload, create a starter mapping, correct it visually, preview, fill, and
   reopen the result in their normal viewer.
4. Have them repeat the fill with a second synthetic record using the saved mapping.
5. Record every correction and failure category without copying personal values.
6. Repeat weekly for four weeks; do not infer retention from GitHub stars or one successful demo.

## Success thresholds

| Measure | Pilot threshold |
|---|---:|
| Correct mappings before manual correction | at least 70% |
| Correct mappings after one saved profile | at least 95% |
| First template to reviewed PDF | under 3 minutes |
| Repeat fill using a saved mapping | under 30 seconds |
| Completed fills without silent field loss | 100% |
| Teams returning in at least 3 of 4 weeks | at least 50% |
| Teams willing to pay or fund support | at least 2 of 5 |

Treat a missing or wrong value as a failure even if a PDF was generated. AI-assisted decisions must
remain visibly reviewable; never raise the confidence threshold merely to improve the metric.

## Interview prompts

- What triggers this form, and where does its data already live?
- Which mistakes create rework, compliance risk, or harm?
- Who reviews the completed PDF and in which viewer?
- What prevents using a hosted document API today?
- Which step would make you stop using this after the first week?
- Would you pay for hosted operation, private deployment, or support? At what volume?

Continue only when repeat usage and saved-mapping accuracy improve. If teams need scanned PDFs,
signatures, or a consumer editor more than repeat AcroForm automation, narrow or change the segment.
