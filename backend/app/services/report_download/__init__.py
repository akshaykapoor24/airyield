"""Workspace → Report download: one combined .xlsx of a user's Vendors → Statements uploads.

The package is split so that almost everything is PURE and unit-testable without a DB:

  types.py      shared dataclasses (DocKey, Period, ReportOptions, UploadMeta, LinkResult, MapCtx …)
  columns.py    the 62 Combined columns, transaction-type vocabulary, flag legend, net reasons
  normalize.py  money / date / ticket-number normalisation (Python + mirrored SQL date key)
  pii.py        which source fields may be exported
  lcc_codes.py  LCC Detailed tax-code classifier
  registry.py   one ReportSource per statement type (15)
  mappers/      per-source detail-sheet columns and row → Combined mapping
  linking.py    BSP selection index, TGQ / memo / NDC / LCC / TP membership, de-duplication
  summary.py    Summary sheet accumulator;  readme.py  Read Me sheet rows
  workbook.py   write-only openpyxl workbook with sheet split + cell safety

Async, DB-touching code lives in queries.py / selection.py / builder.py / jobs.py, and the
Celery task in app/workers/report_tasks.py. Scope is always the calling user's own uploads
(tenant_id AND created_by_id), exactly like every Vendors → Statements screen.
"""
