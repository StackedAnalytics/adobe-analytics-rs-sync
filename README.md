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

- Python 3.6+ (tested with 3.9)
- Adobe Developer Console project with OAuth Server-to-Server credentials
- Analytics product profile with admin access to relevant report suites

## Installation

```bash
# Install dependencies
pip install aanalytics2 python-dotenv

# Clone or download the scripts
# - adobe_analytics_rs_sync_aanalytics2.py  (main sync tool)
# - test_connection.py                       (connection tester)
# - .env.example                             (environment template)
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

### 3. Test Your Connection

```bash
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

```bash
python adobe_analytics_rs_sync_aanalytics2.py
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

Then set report suite IDs via shell environment variables.

### Passing Values Directly in Code

```python
from adobe_analytics_rs_sync_aanalytics2 import ReportSuiteSynchronizer, ReportSuiteConfig, OAuthConfig

# Override environment variables
oauth = OAuthConfig(
    org_id="YOUR_ORG_ID@AdobeOrg",
    client_id="your_client_id",
    client_secret="your_secret"
)
config_file = oauth.save_to_file("my_config.json")

rs_config = ReportSuiteConfig(
    production_rsid="mycompanyprod",
    dev_rsid="mycompanydev",
    staging_rsid="mycompanystg"
)

sync = ReportSuiteSynchronizer(config_file, rs_config)
```

### Sync Specific Configuration Types

```python
# Sync only eVars
sync.sync_evars(["mycompanydev", "mycompanystg"])

# Sync only props
sync.sync_props(["mycompanydev"])

# Sync only events
sync.sync_events(["mycompanystg"])
```

### Compare Two Report Suites

```python
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
├── .env.example                     # Environment template (commit this)
├── .env                             # Your environment config (do NOT commit!)
├── config_analytics_oauth.json      # Your OAuth credentials (do NOT commit!)
├── adobe_analytics_rs_sync_aanalytics2.py   # Main sync tool
├── test_connection.py               # Connection tester
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

Add to your `.gitignore`:
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