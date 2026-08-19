# Tax Categorizer

Ingests purchase records (CSV/XLSX exports, PDFs, receipt photos) and determines which
line items are tax-deductible, using a rule engine first and a Claude fallback for
anything ambiguous.

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```

Edit `.env` and set `ANTHROPIC_API_KEY`.

**Windows OCR note**: scanned PDFs and receipt photos need the Tesseract-OCR binary
(not pip-installable). Install from the
[UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki), then set
`TESSERACT_CMD` in `.env` if `tesseract.exe` isn't on your `PATH`.

## Current status

Done and verified: CSV/XLSX ingestion, digital-PDF ingestion (text-layer extraction +
generic receipt line-item parsing, hardened against real Costco receipts, including
multi-unit "N @ price" quantity lines and payment-tender line filtering), the
rule-based categorization engine, a Claude categorization fallback that can look up
cryptic receipt codes via web search to identify the real product before deciding
(see below), a filename-based override for Costco gas-station receipts (see below),
and the FastAPI + HTMX web dashboard: upload files or point at a folder on disk,
background processing with duplicate-file detection, a review/override table, a
final spreadsheet export split into Tax Deductible / Not Deductible sheets, and a
checked-sheet import so hand-marked Deductible y/x calls persist to the database
instead of being lost on the next export. Not yet built: scanned-PDF/image OCR and a
second ruleset (e.g. Schedule A).

### How Claude decides, and when it asks you

Every line item hits the rule engine first (free, instant, no API call). Anything
unmatched goes to Claude, which now has a `web_search` tool: for a cryptic receipt
code like `1193179 KS SMALL **`, it looks up the actual product (e.g. Kirkland
Signature dog food) instead of guessing from the abbreviation, and that real name
replaces the code in the record (`app/categorization/claude_categorize.py`). Claude
only sets `needs_review` when the deductibility is genuinely ambiguous once it knows
what the item is - a cleaning product or a folding chair that's plausibly business or
personal use, for example - not just because the receipt text was hard to read. In
practice this means most grocery/household items on a Costco receipt get confidently
auto-categorized as non-deductible, and only true business-or-personal judgment calls
land in the review queue.

### Getting your own receipts in (e.g. Costco)

Costco doesn't offer a bulk transaction export, so pull receipts manually:
online orders and in-warehouse purchase history (if your membership is linked) are
both under **costco.com -> Orders & Purchases**. Save each receipt as a PDF (browser
"Print -> Save as PDF") into a folder, named `Costco_MM-DD_<receipt id>.pdf`. If the
receipt id is a single digit, it's treated as a gas-station purchase and
auto-categorized as deductible vehicle fuel, bypassing the rule engine and Claude
entirely (see `app/ingestion/costco_filename.py`).

## Run the web dashboard

```
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/, pick a ruleset, and either point at a folder already on
disk (e.g. `Costco_Receipts`, processed in place - no need to select hundreds of files
in a browser dialog) or upload files directly (CSV/XLSX/PDF). Processing runs in the
background. The status page auto-refreshes until it's done, then links to a review
table where you can filter to items needing review, override category/deductible/
percentage/quantity inline, and confirm ambiguous items as-is.

**Duplicates**: every source file's original filename is checked against everything
already ingested; a repeat (e.g. re-running folder ingestion after adding a few new
receipts) is skipped automatically rather than double-counted. Every line item also
gets a stable `item_uid` like `2025-11-29_3` (date + sequence number, unique across
the whole database) so rows are easy to reference and spot duplicates of by eye.

**Export**: the review page's "Export Spreadsheet (.xlsx)" link produces the final
report - a "Tax Deductible" sheet and a "Not Deductible" sheet (plus "Uncategorized"
for anything that never got a verdict, e.g. an unreadable page), each with item,
date, quantity, and cost, alongside the assigned category for reference. A raw CSV
export is also available for scripting.

The leading "All Items" sheet has a "Deductible" column you can hand-fill with "y"/"x"
per row as you review. Those marks aren't captured automatically - export the sheet,
mark it up in Excel, then use "Import a Checked Sheet" on the home page to upload it
back; the app matches rows by Item UID and saves your y/x calls to the database. Every
export after that pre-fills already-reviewed rows with their saved mark, so re-running
ingestion or re-exporting never blanks out work you've already done - only rows you
haven't reviewed yet come back blank.

Image receipts (JPG/PNG) are accepted by the upload form but OCR isn't implemented
yet, so they'll be reported as a per-file error rather than processed.

## CLI smoke tests

```
python scripts/ingest_csv_smoke_test.py tests/fixtures/sample_transactions.csv us_self_employed_schedule_c
python scripts/ingest_pdf_smoke_test.py tests/fixtures/sample_receipt.pdf us_self_employed_schedule_c
python scripts/ingest_folder.py Costco_Receipts us_self_employed_schedule_c --limit 5
```

Useful for testing ingestion/categorization changes without going through the browser.
Each prints category, deductible status, and rationale per row/line item. The PDF
parser is a generic heuristic (print-header site name or known-vendor hint = vendor,
date-shaped tokens = receipt date, "description ... $amount" lines = items,
subtotal/tax/tender/coupon lines excluded) tuned against real Costco receipts - other
vendors' PDFs may need tweaks to `app/ingestion/receipt_parser.py`. These scripts
don't do duplicate-file detection or `item_uid` assignment (those live in
`app/web/processing.py`) - for real ingestion runs, use the web dashboard.

## Rulesets

Tax categories live as data, not code, in `config/rulesets/*.yaml`. Each category has
keyword matchers, a deductible flag, a deduction percentage (e.g. 0.5 for meals), and
an optional `requires_manual_review` flag. Add a new YAML file here to support a
different filer type; no application code changes needed.
