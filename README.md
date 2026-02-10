# Invoice Processing Automation

Email → PDF/Image → AI Extraction → Validation → Approval → Google Sheets → Slack

## Problem
Finance teams spend 5–10 hours per week manually entering invoice data, leading to errors, delays, and poor visibility.

## Solution
An automated invoice processing pipeline using AI-based extraction with rule-based validation and approval workflows.

## Features
- PDF invoice ingestion
- AI-powered structured data extraction
- Duplicate and validation checks
- Automatic approval routing for high-value invoices
- Google Sheets integration
- Slack notifications

## Tech Stack
- Python
- FastAPI
- Claude API
- pdfplumber
- Google Sheets API
- Slack Webhooks

## Business Impact
- ~70% reduction in manual data entry time
- Faster approvals
- Improved financial accuracy

> Note: `eval()` is used for demo simplicity. Production systems will use safe JSON parsing.
