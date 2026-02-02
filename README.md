# Adobe Analytics Report Suite Sync Tool

A Python utility for synchronizing report suite configurations across Adobe Analytics environments (e.g., production → dev/staging).

## Why This Tool Exists

When managing multiple Adobe Analytics report suites, keeping configurations in sync is tedious and error-prone. This tool automates the process of copying:

- **eVars** (conversion variables)
- **Props** (traffic variables)
- **Success Events**
- **Internal URL Filters**
- **Marketing Channels & Rules**
- **List Variables**

## Important: API Version Note

> ⚠️ **This tool uses the Adobe Analytics 1.4 API**

The 2.0 API does not yet support report suite configuration management. The 1.4 API will reach end-of-life on **August 12, 2026**. Plan to migrate once Adobe adds these features to the 2.0 API.

## Requirements

- [Adobe Developer Console](https://developer.adobe.com/console) project with OAuth Server-to-Server credentials
- [Analytics product profile with admin access](https://experienceleague.adobe.com/en/docs/analytics/admin/admin-console/admin-roles-in-analytics) to relevant report suites

## Installation

Clone this repo to an empty dir and `cd` into it.
```bash
git clone https://github.com/StackedAnalytics/adobe-analytics-rs-sync.git

cd adobe-analytics-rs-sync
```

### Using [uv](https://docs.astral.sh/uv/) (recommended)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies (creates venv and installs everything)
uv sync
```

### Using pip

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install aanalytics2 python-dotenv
```

## Quick Start

### 1. Set Up Adobe Developer Console Credentials

1. Go to [Adobe Developer Console](https://developer.adobe.com/console/)
2. Create a new project (or use an existing one)
3. Add the **Adobe Analytics** API
4. Create an **OAuth Server-to-Server** credential
5. Assign the credential to a product profile with Analytics admin access

### 2. Create Your `.env` File

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Adobe OAuth Server-to-Server Credentials
# Get these from Adobe Developer Console
AA_ORG_ID=YOUR_ORG_ID@AdobeOrg
AA_CLIENT_ID=your_client_id_here
AA_CLIENT_SECRET=your_client_secret_here

# Report Suite IDs
AA_PRODUCTION_RSID=mycompanyprod
AA_DEV_RSID=mycompanydev
AA_STAGING_RSID=mycompanystg
```

> 💡 **That's it!** All configuration is in one place. No need for a separate JSON file.

### 3. (Optional) Test Your Connection

```bash
# If using uv
uv run test_connection.py

# If using pip/venv
python test_connection.py
```

Expected output:
```
==================================================
ADOBE ANALYTICS CONNECTION TEST
==================================================

[1] Checking config file...
    ✓ Found: config_analytics_oauth.json

[2] Authenticating with Adobe IMS...
    ✓ Authentication successful

[3] Getting company information...
    ✓ Found 1 company(ies):
      - My Company (ID: mycompany)

[4] Testing 1.4 API connection (LegacyAnalytics)...
    ✓ LegacyAnalytics client created for: My Company

[5] Testing 1.4 API call (listing report suites)...
    ✓ Found 3 report suite(s):
      - mycompanyprod: Production
      - mycompanydev: Development
      - mycompanystg: Staging

==================================================
CONNECTION TEST PASSED ✓
==================================================
```

### 4. Run the Sync

The tool has a **simple API** — everything loads from your `.env` file automatically:

```bash
# If using uv
uv run adobe_analytics_rs_sync.py

# If using pip/venv
python adobe_analytics_rs_sync.py
```

The script will:
1. ✓ Connect to Adobe Analytics
2. ✓ Create a backup of target report suites
3. ✓ Compare configurations between source and targets
4. ✓ Perform a dry run (shows what would change)
5. ⏸ Wait for you to uncomment the actual sync

## Configuration

### Environment Variables

All configuration is done via environment variables (loaded from `.env` file):

| Variable | Required | Description |
|----------|----------|-------------|
| `AA_ORG_ID` | Yes | Adobe Organization ID (ends with `@AdobeOrg`) |
| `AA_CLIENT_ID` | Yes | OAuth Client ID from Developer Console |
| `AA_CLIENT_SECRET` | Yes | OAuth Client Secret from Developer Console |
| `AA_SCOPES` | No | OAuth scopes (has sensible default) |
| `AA_PRODUCTION_RSID` | Yes | Source report suite (production) |
| `AA_DEV_RSID` | Yes | Target report suite (development) |
| `AA_STAGING_RSID` | No | Target report suite (staging) |
| `AA_CONFIG_FILE` | No | Path to JSON config (only if not using env vars) |

### Using a `.env` File (Recommended)

1. Copy `.env.example` to `.env`
2. Fill in your values
3. Run the script — it loads automatically via `python-dotenv`

```bash
cp .env.example .env
# Edit .env with your values
python test_connection.py
```

### Alternative: JSON Config File

If you prefer a JSON config file (or can't use `python-dotenv`), create `config_analytics_oauth.json`:

```json
{
  "org_id": "YOUR_ORG_ID@AdobeOrg",
  "client_id": "your_client_id",
  "secret": "your_client_secret",
  "scopes": "openid,AdobeID,read_organizations,additional_info.projectedProductContext"
}
```

The tool will automatically detect and use this file if present. Set report suite IDs via shell environment variables.

## Usage

### Basic Usage

```python
from adobe_analytics_rs_sync import ReportSuiteSynchronizer, SyncConfig

# Simple! Everything loads from .env automatically
sync = ReportSuiteSynchronizer()
sync.connect()

# Run a full sync (dry run first!)
# Default: syncs only ENABLED variables (safest)
sync.sync_all(dry_run=True)

# If everything looks good, do the actual sync
# sync.sync_all(dry_run=False)
```

### Advanced Options (New in v1.1+)

#### Sync Scope Control

```python
# Default: Sync only ENABLED variables (safest)
sync.sync_all(dry_run=True)

# Include disabled variables
sync.sync_all(dry_run=True, include_disabled=True)

# Sync only CHANGED variables (most efficient - reduces API calls)
sync.sync_all(dry_run=True, sync_changed_only=True)

# Combine: Sync all changed variables (enabled + disabled)
sync.sync_all(dry_run=True, include_disabled=True, sync_changed_only=True)
```

#### Using SyncConfig for Complex Cases

```python
from adobe_analytics_rs_sync import SyncConfig

# Create reusable configuration
prod_config = SyncConfig(
    dry_run=False,
    include_disabled=False,  # Only enabled (safest)
    sync_changed_only=True   # Only what changed (efficient)
)

dev_config = SyncConfig(
    dry_run=False,
    include_disabled=True,   # All variables
    sync_changed_only=False  # Everything
)

# Use config objects
sync.sync_all(config=prod_config)
sync.sync_evars(["dev_rsid"], config=dev_config)
```

#### Sync Specific Variable Types

```python
# Sync only eVars (with options)
sync.sync_evars(["dev_rsid", "stg_rsid"], sync_changed_only=True)

# Sync only props (include disabled)
sync.sync_props(["dev_rsid"], include_disabled=True)

# Sync only events
sync.sync_events(["dev_rsid"], sync_changed_only=True)
```

### Advanced: Override Configuration

```python
from adobe_analytics_rs_sync import ReportSuiteSynchronizer, ReportSuiteConfig, OAuthConfig

# Override specific settings while keeping env defaults for others
rs_config = ReportSuiteConfig(
    production_rsid="mycompanyprod",
    dev_rsid="mycompanydev",
    staging_rsid="mycompanystg"
)

sync = ReportSuiteSynchronizer(rs_config=rs_config)
sync.connect()
```

## What's New in v1.1+

### ⚠️ Behavior Change

**Old behavior (v1.0):**
- Synced ALL variables (including disabled) by default
- Dry run preview only showed enabled variables (misleading)

**New behavior (v1.1+):**
- Syncs only ENABLED variables by default (safer, matches dry run)
- Dry run preview accurately shows what will be synced
- Add `include_disabled=True` to get old behavior if needed

### New Features

1. **Filtered Sync** - Control whether to sync enabled-only or all variables
2. **Change Detection** - Sync only variables that actually changed (faster, safer)
3. **SyncConfig** - Reusable configuration objects for complex setups
4. **Enhanced Logging** - Clear statistics on what's being synced

### Migration Guide

```python
# Your existing code still works, but is now SAFER
# (syncs only enabled variables instead of all)
sync.sync_all(dry_run=True)  # ✅ Safer default behavior

# To get old behavior (sync all variables):
sync.sync_all(dry_run=True, include_disabled=True)

# New efficient option (sync only what changed):
sync.sync_all(dry_run=True, sync_changed_only=True)
```

### Compare Two Report Suites

```python
import json
from adobe_analytics_rs_sync import ReportSuiteSynchronizer

sync = ReportSuiteSynchronizer()
sync.connect()

comparison = sync.compare_report_suites("mycompanyprod", "mycompanydev")
print(json.dumps(comparison, indent=2))
```

Output:
```json
{
  "rsid1": "mycompanyprod",
  "rsid2": "mycompanydev",
  "differences": {
    "evars": {
      "mycompanyprod_enabled": 45,
      "mycompanydev_enabled": 42,
      "only_in_first": {"15": "Campaign ID", "23": "User Type"},
      "only_in_second": {}
    }
  }
}
```

### Backup and Restore

```python
from adobe_analytics_rs_sync import ReportSuiteSynchronizer

sync = ReportSuiteSynchronizer()
sync.connect()

# Create backup
backup = sync.backup_report_suite("mycompanydev")
# Saves to: backup_mycompanydev_20250123_143052.json

# Restore from backup
sync.restore_from_backup(
    "backup_mycompanydev_20250123_143052.json",
    target_rsids=["mycompanydev"],
    configs_to_restore=["evars", "props"]  # Optional: restore specific configs only
)
```

## File Structure

```
.
├── README.md
├── .env.example                     # Environment template
├── .env                             # Your environment config (do NOT commit!)
├── config_analytics_oauth.json      # Optional OAuth credentials file (do NOT commit!)
├── adobe_analytics_rs_sync.py       # Main sync tool
└── backup_*.json                    # Auto-generated backups
```

## Configuration Options Synced

| Config Type | Get Method | Save Method |
|-------------|------------|-------------|
| eVars | `ReportSuite.GetEvars` | `ReportSuite.SaveEvars` |
| Props | `ReportSuite.GetProps` | `ReportSuite.SaveProps` |
| Events | `ReportSuite.GetEvents` | `ReportSuite.SaveEvents` |
| Internal URL Filters | `ReportSuite.GetInternalURLFilters` | `ReportSuite.SaveInternalURLFilters` |
| Marketing Channels | `ReportSuite.GetMarketingChannels` | `ReportSuite.SaveMarketingChannels` |
| Marketing Channel Rules | `ReportSuite.GetMarketingChannelRules` | `ReportSuite.SaveMarketingChannelRules` |
| List Variables | `ReportSuite.GetListVariables` | `ReportSuite.SaveListVariables` |

## Safety Features

1. **Dry Run Mode** — Preview all changes before applying
2. **Automatic Backups** — Creates JSON backup before any sync
3. **Comparison Tool** — See exactly what differs between report suites
4. **Granular Sync** — Sync individual config types separately
5. **Restore Capability** — Roll back from any backup file

## Troubleshooting

### "Authentication failed"

- Verify your `client_id` and `secret` in the config file
- Ensure the OAuth credential is added to a product profile
- Check that the product profile has Analytics access

### "No companies found"

- Your OAuth credential may not be assigned to a product profile
- The product profile may not have Analytics permissions

### "No report suites found"

- The product profile needs access to specific report suites
- Check Admin Console → Product Profiles → Analytics → Report Suites

### "Failed to save eVars/props/events"

- Ensure your product profile has **admin** access, not just reporting access
- Some settings may be locked at the organization level

## Security Notes

⚠️ **Never commit secrets to version control!**

By default, the `.gitignore` includes secret files to keep you from accidentally committing them.

```gitignore
# Credentials and secrets
.env
config_analytics_oauth.json
.aa_config_from_env.json

# Backups may contain sensitive config
backup_*.json

# Python
*.log
__pycache__/
*.pyc
```

The `.env.example` file is safe to commit — it contains only placeholder values.

## API Documentation

- [Adobe Analytics 1.4 API — Report Suite Get Methods](https://developer.adobe.com/analytics-apis/docs/1.4/guides/admin/report-suite/get/)
- [Adobe Analytics 1.4 API — Report Suite Save Methods](https://developer.adobe.com/analytics-apis/docs/1.4/guides/admin/report-suite/save/)
- [aanalytics2 Package Documentation](https://github.com/pitchmuc/adobe-analytics-api-2.0)

## License

MIT License — use freely, attribution appreciated.

## Contributing

Issues and pull requests welcome! Please test thoroughly with dry runs before submitting changes.