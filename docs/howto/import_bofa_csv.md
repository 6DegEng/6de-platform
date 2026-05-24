# How To: Import Bank of America Transactions via CSV

## Overview

The Accounting page's "CSV Import" tab lets you upload a Bank of America CSV export and auto-categorize transactions using the platform's rules engine. This is Phase 0 of the bank integration -- manual CSV upload now, automated Plaid sync in a future phase.

## Step 1: Export CSV from Bank of America

1. Log in to [bankofamerica.com](https://www.bankofamerica.com)
2. Navigate to your business checking/savings account
3. Click **Account Activity** or **Statements & Documents**
4. Set the date range you want to import
5. Click **Download** (or the download icon)
6. Select **CSV** format
7. Save the file to your computer

The exported CSV has columns: `Date, Description, Amount, Running Bal.`

## Step 2: Set Up a Bank Connection (First Time Only)

1. Open the platform at `http://localhost:8502`
2. Navigate to **Accounting** in the sidebar
3. Click the **CSV Import** tab
4. Under "Bank Connection", fill in:
   - **Institution Name**: Bank of America (pre-filled)
   - **Account Last 4 Digits**: e.g., `1234`
   - **Account Type**: Checking / Savings / Credit
5. Click **Save Connection**

You only need to do this once per bank account. On future imports, select the existing connection from the dropdown.

## Step 3: Upload the CSV

1. In the CSV Import tab, click **Browse files** (or drag and drop)
2. Select the CSV file exported from BofA
3. The parser runs immediately and shows a preview

## Step 4: Review the Preview

The preview shows each transaction with:

- **Date**: Parsed from the CSV
- **Description**: Transaction description
- **Amount**: Negative = expense, positive = income
- **Balance**: Running balance (if present in CSV)
- **Category**: Auto-assigned by the rules engine
- **Status**:
  - **Auto** (green): A categorization rule matched
  - **Review** (orange): No rule matched; you will need to categorize manually

Summary metrics show total rows, how many were auto-categorized, how many need review, and the date range.

## Step 5: Import

1. Review the preview to ensure the data looks correct
2. Click the **Import N Transactions** button
3. The platform:
   - Writes all transactions to the database with `source='csv'`
   - Skips any duplicates (same date + amount + description)
   - Records the import in the sync_runs audit trail
4. A success message shows how many were imported and how many duplicates were skipped

## Step 6: Handle "Needs Review" Transactions

After import, uncategorized transactions appear in the **Categorization** tab under "Needs Review":

1. Switch to the **Categorization** tab
2. Find transactions without a category
3. Either:
   - **Manual**: Use the "Assign Category" form to pick a category for each
   - **Add a Rule**: Scroll to "Add New Rule", create a regex pattern that matches the vendor, and re-run auto-categorization

## Tips

- **Weekly imports** work well: export Friday, import Monday morning
- **Re-importing the same file** is safe -- duplicates are automatically skipped
- **Multiple accounts**: Create a separate bank connection for each account (checking, savings, credit card)
- **Custom categories**: Add new categorization rules in the Categorization tab before importing to maximize auto-categorization
- **Date range**: You can import overlapping date ranges without worrying about duplicates

## Troubleshooting

**"No valid transactions found"**: The CSV may have an unexpected format. Check that it has at least 3 columns (Date, Description, Amount). Some BofA account types export different column layouts.

**Parser warnings**: Expand the warnings section to see which rows were skipped and why (invalid dates, empty descriptions, etc.).

**All transactions show as duplicates**: You already imported this file. Check the Transactions tab to confirm the data is there.

**Wrong categories**: Edit or add rules in the Categorization tab. The rules engine uses regex patterns with priority ordering -- lower priority numbers are checked first.
