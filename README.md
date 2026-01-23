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
# Install the aanalytics2 package
uv sync
# or
pip install aanalytics2

# Clone or download the scripts
# - adobe_analytics_rs_sync.py  (main sync tool)
# - test_connection.py (test your Adobe API connection without running the utility)
```

## Quick Start

### 1. Set Up Adobe Developer Console Credentials

> [!TIP]
> If you already have a project with the Adobe Analytics API enabled and an OAuth server-to-server credential, skip to step 2

1. Go to [Adobe Developer Console](https://developer.adobe.com/console/)
2. Create a new project (or use an existing one)
3. Add the **Adobe Analytics** API
4. Create an **OAuth Server-to-Server** credential
5. Assign the credential to a product profile with Analytics admin access

### 2. Create Configuration File

Create `config_analytics_oauth.json` in your working directory:

```json
{
  "org_id": "YOUR_ORG_ID@AdobeOrg",
  "client_id": "your_client_id",
  "secret": "your_client_secret",
  "scopes": "openid,AdobeID,read_organizations,additional_info.projectedProductContext,additional_info.job_function"
}
```

> 💡 **Tip:** Run `test_connection.py` first — it will create a sample config file for you.

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

### 4. Configure Report Suites

Edit `main.py` and update the `ReportSuiteConfig` class:

```python
@dataclass
class ReportSuiteConfig:
    production_rsid: str = "mycompanyprod"    # Source of truth
    dev_rsid: str = "mycompanydev"            # Target
    staging_rsid: str = "mycompanystg"        # Target
```

### 5. Run the Sync

```bash
python main.py
```

The script will:
1. ✓ Connect to Adobe Analytics
2. ✓ Create a backup of target report suites
3. ✓ Compare configurations between source and targets
4. ✓ Perform a dry run (shows what would change)
5. ⏸ Wait for you to uncomment the actual sync

## Usage Examples

### Dry Run (Preview Changes)

```python
from adobe_analytics_rs_sync import ReportSuiteSynchronizer, ReportSuiteConfig

sync = ReportSuiteSynchronizer("config_analytics_oauth.json", ReportSuiteConfig())
sync.connect()

# See what would be synced without making changes
results = sync.sync_all(dry_run=True)
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
├── config_analytics_oauth.json      # Your credentials (do not commit!)
├── adobe_analytics_rs_sync.py       # Main sync tool
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

⚠️ **Never commit `config_analytics_oauth.json` to version control!**

Add to your `.gitignore`:
```
config_analytics_oauth.json
backup_*.json
*.log
```

## API Documentation

- [Adobe Analytics 1.4 API — Report Suite Get Methods](https://developer.adobe.com/analytics-apis/docs/1.4/guides/admin/report-suite/get/)
- [Adobe Analytics 1.4 API — Report Suite Save Methods](https://developer.adobe.com/analytics-apis/docs/1.4/guides/admin/report-suite/save/)
- [aanalytics2 Package Documentation](https://github.com/pitchmuc/adobe-analytics-api-2.0)

## License

MIT License — use freely, attribution appreciated.

## Contributing

Issues and pull requests welcome! Please test thoroughly with dry runs before submitting changes.