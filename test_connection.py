#!/usr/bin/env python3
"""
Simple Connection Test for Adobe Analytics
===========================================

Run this script to verify your credentials work before running the full sync.

Usage:
    python test_connection.py

Prerequisites:
    1. pip install aanalytics2 python-dotenv
    2. Create .env file with your credentials (see .env.example)
       OR create config_analytics_oauth.json
"""

import aanalytics2 as api2
import json
import os
from pathlib import Path

# Load environment variables from .env file (if it exists)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_oauth_from_env():
    """Check if OAuth credentials are set in environment variables"""
    org_id = os.getenv("AA_ORG_ID", "")
    client_id = os.getenv("AA_CLIENT_ID", "")
    client_secret = os.getenv("AA_CLIENT_SECRET", "")
    scopes = os.getenv(
        "AA_SCOPES",
        "openid,AdobeID,read_organizations,additional_info.projectedProductContext,additional_info.job_function"
    )
    
    if org_id and client_id and client_secret:
        return {
            "org_id": org_id,
            "client_id": client_id,
            "secret": client_secret,
            "scopes": scopes
        }
    return None


def create_config_if_missing():
    """Create a sample config file if no configuration exists"""
    config_file = os.getenv("AA_CONFIG_FILE", "config_analytics_oauth.json")
    
    # First check if env vars are set
    env_config = get_oauth_from_env()
    if env_config:
        # Write temp config for aanalytics2
        temp_file = ".aa_config_from_env.json"
        with open(temp_file, 'w') as f:
            json.dump(env_config, f, indent=2)
        return temp_file, True  # Return file path and flag indicating env vars used
    
    # Check for existing config file
    if Path(config_file).exists():
        return config_file, False
    
    # Create sample config
    config = {
        "org_id": "DUMMY_ORG_ID@AdobeOrg",
        "client_id": "dummy_client_id_abc123xyz789",
        "secret": "dummy_client_secret_p@ssw0rd123!secret",
        "scopes": "openid,AdobeID,read_organizations,additional_info.projectedProductContext,additional_info.job_function"
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"✗ No credentials found!")
    print(f"\n  Option 1: Create a .env file with:")
    print(f"    AA_ORG_ID=YOUR_ORG_ID@AdobeOrg")
    print(f"    AA_CLIENT_ID=your_client_id")
    print(f"    AA_CLIENT_SECRET=your_client_secret")
    print(f"\n  Option 2: Update the config file created at:")
    print(f"    {config_file}")
    return None, False


def test_connection():
    """Test the connection to Adobe Analytics"""
    
    print("=" * 50)
    print("ADOBE ANALYTICS CONNECTION TEST")
    print("=" * 50)
    
    # Step 1: Check config file
    print("\n[1] Checking configuration...")
    config_file, using_env = create_config_if_missing()
    if not config_file:
        return False
    
    if using_env:
        print("    ✓ Using credentials from environment variables")
    else:
        print(f"    ✓ Using config file: {config_file}")
    
    # Step 2: Import config (this triggers authentication)
    print("\n[2] Authenticating with Adobe IMS...")
    try:
        api2.importConfigFile(config_file)
        print("    ✓ Authentication successful")
    except Exception as e:
        print(f"    ✗ Authentication failed: {e}")
        return False
    
    # Step 3: Get company info
    print("\n[3] Getting company information...")
    try:
        login = api2.Login()
        companies = login.getCompanyId()
        
        if not companies:
            print("    ✗ No companies found for this account")
            return False
        
        print(f"    ✓ Found {len(companies)} company(ies):")
        for c in companies:
            print(f"      - {c.get('companyName')} (ID: {c.get('globalCompanyId')})")
        
        # Use first company
        company = companies[0]
        company_name = company.get('companyName')
        global_company_id = company.get('globalCompanyId')
        
    except Exception as e:
        print(f"    ✗ Failed to get company info: {e}")
        return False
    
    # Step 4: Test LegacyAnalytics (1.4 API) connection
    print("\n[4] Testing 1.4 API connection (LegacyAnalytics)...")
    try:
        legacy = api2.LegacyAnalytics(company_name=company_name)
        print(f"    ✓ LegacyAnalytics client created for: {company_name}")
    except Exception as e:
        print(f"    ✗ Failed to create LegacyAnalytics client: {e}")
        return False
    
    # Step 5: Test a simple 1.4 API call - get report suites
    print("\n[5] Testing 1.4 API call (listing report suites)...")
    try:
        # This is a simple call that should work if auth is correct
        result = legacy.postData(
            method="Company.GetReportSuites",
            data={}
        )
        
        if result and 'report_suites' in result:
            rs_list = result['report_suites']
            print(f"    ✓ Found {len(rs_list)} report suite(s):")
            for rs in rs_list[:5]:  # Show first 5
                print(f"      - {rs.get('rsid')}: {rs.get('site_title')}")
            if len(rs_list) > 5:
                print(f"      ... and {len(rs_list) - 5} more")
        else:
            print(f"    ⚠ Unexpected response: {result}")
            
    except Exception as e:
        print(f"    ✗ 1.4 API call failed: {e}")
        return False
    
    # Step 6: Test Analytics (2.0 API) connection
    print("\n[6] Testing 2.0 API connection (Analytics)...")
    try:
        analytics = api2.Analytics(global_company_id)
        print(f"    ✓ Analytics client created for: {global_company_id}")
        
        # Try to get report suites via 2.0 API
        rs_df = analytics.getReportSuites()
        if rs_df is not None and not rs_df.empty:
            print(f"    ✓ 2.0 API working - found {len(rs_df)} report suites")
        
    except Exception as e:
        print(f"    ⚠ 2.0 API test failed (non-critical): {e}")
    
    # Step 7: Show configured report suites from env
    print("\n[7] Checking report suite configuration...")
    prod_rsid = os.getenv("AA_PRODUCTION_RSID", "")
    dev_rsid = os.getenv("AA_DEV_RSID", "")
    staging_rsid = os.getenv("AA_STAGING_RSID", "")
    
    if prod_rsid and dev_rsid:
        print(f"    ✓ Report suites configured:")
        print(f"      - Production: {prod_rsid}")
        print(f"      - Dev:        {dev_rsid}")
        if staging_rsid:
            print(f"      - Staging:    {staging_rsid}")
    else:
        print(f"    ⚠ Report suite IDs not configured in environment")
        print(f"      Add to .env: AA_PRODUCTION_RSID, AA_DEV_RSID, AA_STAGING_RSID")
    
    # Clean up temp config if we created one
    if using_env and Path(".aa_config_from_env.json").exists():
        Path(".aa_config_from_env.json").unlink()
    
    # Success!
    print("\n" + "=" * 50)
    print("CONNECTION TEST PASSED ✓")
    print("=" * 50)
    print(f"\nYou can now use:")
    print(f"  Company Name:      {company_name}")
    print(f"  Global Company ID: {global_company_id}")
    
    return True


if __name__ == "__main__":
    success = test_connection()
    exit(0 if success else 1)