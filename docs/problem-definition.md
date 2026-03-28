# Problem Definition

## The Manual Invoice Processing Problem

### Who Has This Problem

Finance teams at growing companies — typically 20 to 200 employees — processing 50 to 500 invoices per month. At this scale, the volume is too high for casual ad-hoc handling, but too low to justify a dedicated AP automation platform (Tipalti, Bill.com, Basware).

A company with 50 employees and 200 monthly invoices typically has one finance admin spending 15–20 hours per week on invoice processing. That is roughly half their working time on data entry.

### The Manual Process (Before This System)

1. **Receive invoice** — via email attachment, supplier portal, or post
2. **Open invoice** — PDF viewer, print if scanned
3. **Re-key fields** — manually type vendor name, invoice number, date, line items, and amount into accounting software (Xero / QuickBooks / spreadsheet)
4. **Apply coding** — assign a GL account code to each line item (manual lookup)
5. **Check for duplicates** — scroll through recent invoices to see if this number was already entered
6. **Route for approval** — email the invoice to the budget owner for sign-off
7. **Mark as approved / post** — update accounting software with approval
8. **File** — move the invoice PDF to the correct folder

Steps 3, 4, and 5 are entirely manual and repeated for every invoice.

### Pain Points

**Manual data entry error rate: 3–7%**
Industry research on manual data entry consistently finds 3–7% keystroke error rates. For financial data, even a 1% error rate means incorrect amounts, wrong vendor names, or missing invoice numbers. These surface later as reconciliation failures or audit exceptions.

**Duplicate payments: 0.1–0.5% of invoice volume**
Without systematic deduplication, duplicate invoices (re-sent by suppliers, forwarded from different email addresses, or scanned twice) get paid twice. At £2,400 average invoice value and 200 invoices/month, a 0.1% duplicate rate is £2,400/month in overpayments.

**No audit trail**
Spreadsheet-based workflows have no immutable record of who approved what and when. This creates compliance gaps and makes dispute resolution difficult.

**Inconsistent validation**
Different staff members apply different rules for ambiguous invoices: some accept date formats like "March 1st"; others reject them. Currency handling varies. This is impossible to audit and creates inconsistent accounting records.

**Multi-currency friction**
Invoices from international suppliers use symbols (£, €, ¥), words ("GBP", "Euros"), and varying decimal conventions. Manual conversion and normalisation are error-prone and time-consuming.

**Re-keying into multiple systems**
Many companies maintain invoices in both their accounting software and a spreadsheet tracker. Every invoice is entered twice. Some pipe data into a third system (ERP or expense management). Each re-key step multiplies the error surface.

### Cost Estimate

For a 50-person company processing 200 invoices/month:

| Cost source | Amount |
|---|---|
| Finance admin time (15 hrs/week × £25/hr × 4.3 weeks) | £1,612/month |
| Duplicate payment exposure (0.1% × 200 × £2,400 avg) | £480/month |
| Error correction (reconciliation, supplier disputes) | £200/month (est.) |
| **Total** | **~£2,300/month** |

This is the cost the system is designed to eliminate.

### What This System Does Differently

| Manual step | System equivalent |
|---|---|
| Re-key invoice fields | AI extraction (vendor, date, amount, line items) |
| Check for duplicates | SHA-256 content hash, checked on every upload |
| Inconsistent validation | Deterministic validation rules in code |
| No audit trail | Immutable audit log on every review action |
| Multi-currency confusion | Automatic ISO 4217 normalisation |
| Multiple system re-keying | Direct export to Xero CSV / QuickBooks CSV |
| Approval routing | Confidence-based routing to human review queue |

### What This System Does Not Do (Scope Limits)

- **GL coding** — assigning account codes to line items requires knowledge of the company's chart of accounts. This is excluded from v1.
- **Supplier onboarding** — matching invoices to purchase orders requires a PO system. Out of scope.
- **Payment execution** — this system prepares invoices for import; it does not initiate bank transfers.
- **OCR for scanned PDFs** — low-quality scans require vision model calls or dedicated OCR. The image parser handles basic cases; production OCR is a v2 feature.
