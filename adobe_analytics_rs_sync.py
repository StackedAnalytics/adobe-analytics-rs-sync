#!/usr/bin/env python3
"""
Adobe Analytics Report Suite Sync Tool (using aanalytics2)
===========================================================

This script synchronizes report suite configurations from a production (source) 
report suite to dev/staging (target) report suites using the aanalytics2 package.

The aanalytics2 package provides:
- Built-in OAuth Server-to-Server authentication
- Support for both 2.0 and 1.4 APIs via LegacyAnalytics class
- Automatic token management

IMPORTANT NOTES:
- Report suite configuration (eVars, props, events) requires the 1.4 API
- The 2.0 API does NOT support these admin functions yet
- The 1.4 API will reach EOL on August 12, 2026

Installation:
    pip install aanalytics2 python-dotenv

Configuration:
    Create a .env file with your report suite IDs:
    
        AA_PRODUCTION_RSID=mycompanyprod
        AA_DEV_RSID=mycompanydev
        AA_STAGING_RSID=mycompanystg

Documentation:
    https://github.com/pitchmuc/adobe-analytics-api-2.0

Author: Charlie Tysse <charlie@ctysse.net>
Version: 1.1
"""

import aanalytics2 as api2
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

# Load environment variables from .env file (if it exists)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed; will use environment variables directly
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class OAuthConfig:
    """
    OAuth Server-to-Server credentials.
    
    Values are loaded from environment variables with fallback to JSON config file.
    
    Environment variables:
        AA_ORG_ID        - Adobe Organization ID (ends with @AdobeOrg)
        AA_CLIENT_ID     - OAuth Client ID
        AA_CLIENT_SECRET - OAuth Client Secret
        AA_SCOPES        - OAuth Scopes (comma-separated)
    """
    org_id: str = None
    client_id: str = None
    client_secret: str = None
    scopes: str = None
    
    def __post_init__(self):
        """Load from environment variables if not provided"""
        if self.org_id is None:
            self.org_id = os.getenv("AA_ORG_ID", "")
        if self.client_id is None:
            self.client_id = os.getenv("AA_CLIENT_ID", "")
        if self.client_secret is None:
            self.client_secret = os.getenv("AA_CLIENT_SECRET", "")
        if self.scopes is None:
            self.scopes = os.getenv(
                "AA_SCOPES",
                "openid,AdobeID,read_organizations,additional_info.projectedProductContext,additional_info.job_function"
            )
    
    def is_configured(self) -> bool:
        """Check if all required credentials are set"""
        return bool(self.org_id and self.client_id and self.client_secret)
    
    def to_config_dict(self) -> Dict[str, str]:
        """Convert to dictionary format expected by aanalytics2"""
        return {
            "org_id": self.org_id,
            "client_id": self.client_id,
            "secret": self.client_secret,
            "scopes": self.scopes
        }
    
    def save_to_file(self, filename: str) -> str:
        """Save credentials to JSON config file (for aanalytics2 compatibility)"""
        with open(filename, 'w') as f:
            json.dump(self.to_config_dict(), f, indent=2)
        return filename

    def get_config_file(self, default_filename: str = "config_analytics_oauth.json") -> Optional[str]:
        """
        Get config file path, creating from environment variables if needed.

        Priority:
        1. If env vars are set (AA_ORG_ID, etc.), create temp .aa_config_from_env.json
        2. If AA_CONFIG_FILE env var points to existing file, use that
        3. If default config_analytics_oauth.json exists, use that
        4. Return None (no configuration found)

        Returns:
            Path to config file or None if no configuration found
        """
        config_file = os.getenv("AA_CONFIG_FILE", default_filename)

        # If OAuth credentials are in environment, create temp config file
        if self.is_configured():
            logger.info("Using OAuth credentials from environment variables")
            temp_config = ".aa_config_from_env.json"
            self.save_to_file(temp_config)
            return temp_config

        # Check for existing config file
        if Path(config_file).exists():
            logger.info(f"Using config file: {config_file}")
            return config_file

        # No config found
        logger.warning("No OAuth configuration found in environment or config file")
        return None


@dataclass
class ReportSuiteConfig:
    """
    Report suite identifiers for the sync operation.
    
    Values are loaded from environment variables (or .env file) with fallback defaults.
    
    Environment variables:
        AA_PRODUCTION_RSID  - Production report suite (source of truth)
        AA_DEV_RSID         - Development report suite (target)
        AA_STAGING_RSID     - Staging report suite (target)
    """
    production_rsid: str = None
    dev_rsid: str = None
    staging_rsid: str = None
    
    def __post_init__(self):
        """Load from environment variables if not provided"""
        if self.production_rsid is None:
            self.production_rsid = os.getenv("AA_PRODUCTION_RSID", "dummycompanyprod")
        if self.dev_rsid is None:
            self.dev_rsid = os.getenv("AA_DEV_RSID", "dummycompanydev")
        if self.staging_rsid is None:
            self.staging_rsid = os.getenv("AA_STAGING_RSID", "dummycompanystg")
    
    @property
    def target_rsids(self) -> List[str]:
        """Return list of target report suites"""
        return [self.dev_rsid, self.staging_rsid]
    
    def is_using_defaults(self) -> bool:
        """Check if still using dummy default values"""
        return "dummy" in self.production_rsid.lower()


# =============================================================================
# CONFIG FILE GENERATOR
# =============================================================================

def get_or_create_config_file(oauth_config: OAuthConfig, default_filename: str = "config_analytics_oauth.json") -> str:
    """
    DEPRECATED: Use OAuthConfig().get_config_file() instead.

    This function is maintained for backwards compatibility.

    Get config file path, creating from environment variables if needed.

    Priority:
    1. If env vars are set (AA_ORG_ID, AA_CLIENT_ID, AA_CLIENT_SECRET), use those
    2. If AA_CONFIG_FILE env var points to existing file, use that
    3. If default config file exists, use that
    4. Return None if no configuration found

    Returns:
        Path to config file or None
    """
    import warnings
    warnings.warn(
        "get_or_create_config_file() is deprecated. Use OAuthConfig().get_config_file() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return oauth_config.get_config_file(default_filename)


# =============================================================================
# REPORT SUITE SYNC CLASS
# =============================================================================

class ReportSuiteSynchronizer:
    """
    Synchronizes report suite configurations using the aanalytics2 package.
    
    Uses the LegacyAnalytics class to access the 1.4 Admin API endpoints
    for report suite configuration management (eVars, props, events, etc.)
    """
    
    def __init__(
        self,
        config_file: Optional[str] = None,
        rs_config: Optional[ReportSuiteConfig] = None
    ):
        """
        Initialize the synchronizer.

        Args:
            config_file: Path to the aanalytics2 config JSON file.
                        If None, automatically loads from environment variables or
                        existing config_analytics_oauth.json file.
            rs_config: Report suite configuration.
                      If None, automatically loads from environment variables.
        """
        # Auto-configure from environment if not provided
        if config_file is None:
            oauth_config = OAuthConfig()
            config_file = oauth_config.get_config_file()

        if rs_config is None:
            rs_config = ReportSuiteConfig()

        self.config_file = config_file
        self.rs_config = rs_config
        self.legacy_client: Optional[api2.LegacyAnalytics] = None
        self.analytics_client: Optional[api2.Analytics] = None
        self.company_name: Optional[str] = None
        self.global_company_id: Optional[str] = None
        self.sync_results: Dict[str, Any] = {}
        
    def connect(self) -> bool:
        """
        Authenticate and establish connections to Adobe Analytics APIs.
        
        Returns:
            True if connection successful
        """
        logger.info("Connecting to Adobe Analytics...")
        
        try:
            # Import the config file - handles OAuth authentication automatically
            api2.importConfigFile(self.config_file)
            
            # Get company information via Login class
            login = api2.Login()
            company_ids = login.getCompanyId()
            
            if not company_ids:
                logger.error("No companies found for this account")
                return False
            
            # Use first company (or you can specify a particular one)
            company_info = company_ids[0]
            self.company_name = company_info.get('companyName')
            self.global_company_id = company_info.get('globalCompanyId')
            
            logger.info(f"Connected to company: {self.company_name}")
            logger.info(f"Global Company ID: {self.global_company_id}")
            
            # Create LegacyAnalytics instance for 1.4 API (required for admin functions)
            # Note: LegacyAnalytics uses companyName, not globalCompanyId
            self.legacy_client = api2.LegacyAnalytics(company_name=self.company_name)
            
            # Also create Analytics instance for 2.0 API (for dimensions/metrics listing)
            self.analytics_client = api2.Analytics(self.global_company_id, retry=2)
            
            logger.info("Successfully initialized both 1.4 and 2.0 API clients")
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {str(e)}")
            return False
    
    # =========================================================================
    # 1.4 API METHODS - Using LegacyAnalytics.postData()
    # =========================================================================
    
    def _call_14_api(self, method: str, data: Dict) -> Optional[Any]:
        """
        Make a call to the 1.4 Admin API via LegacyAnalytics.
        
        The LegacyAnalytics class wraps the 1.4 API with postData method.
        
        Args:
            method: The API method (e.g., "ReportSuite.GetEvars")
            data: The request payload
            
        Returns:
            API response or None on error
        """
        if not self.legacy_client:
            logger.error("Not connected. Call connect() first.")
            return None
            
        try:
            result = self.legacy_client.postData(method=method, data=data)
            return result
        except Exception as e:
            logger.error(f"1.4 API call failed ({method}): {str(e)}")
            return None
    
    # =========================================================================
    # GET METHODS - Retrieve configurations from source report suite
    # =========================================================================
    
    def get_evars(self, rsid_list: List[str]) -> Optional[List[Dict]]:
        """Retrieve eVar configurations for specified report suites"""
        logger.info(f"Getting eVars for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetEvars", {"rsid_list": rsid_list})
    
    def get_props(self, rsid_list: List[str]) -> Optional[List[Dict]]:
        """Retrieve prop (traffic variable) configurations"""
        logger.info(f"Getting props for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetProps", {"rsid_list": rsid_list})
    
    def get_events(self, rsid_list: List[str]) -> Optional[List[Dict]]:
        """Retrieve success event configurations"""
        logger.info(f"Getting events for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetEvents", {"rsid_list": rsid_list})
    
    def get_internal_url_filters(self, rsid_list: List[str]) -> Optional[List[Dict]]:
        """Retrieve internal URL filter configurations"""
        logger.info(f"Getting internal URL filters for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetInternalURLFilters", {"rsid_list": rsid_list})
    
    def get_marketing_channels(self, rsid_list: List[str]) -> Optional[List[Dict]]:
        """Retrieve marketing channel configurations"""
        logger.info(f"Getting marketing channels for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetMarketingChannels", {"rsid_list": rsid_list})
    
    def get_marketing_channel_rules(self, rsid_list: List[str]) -> Optional[List[Dict]]:
        """Retrieve marketing channel rule configurations"""
        logger.info(f"Getting marketing channel rules for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetMarketingChannelRules", {"rsid_list": rsid_list})
    
    def get_list_variables(self, rsid_list: List[str]) -> Optional[List[Dict]]:
        """Retrieve list variable configurations"""
        logger.info(f"Getting list variables for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetListVariables", {"rsid_list": rsid_list})
    
    def get_classifications(self, rsid_list: List[str], element_list: List[str]) -> Optional[List[Dict]]:
        """
        Retrieve classification configurations for specified elements.
        
        Args:
            rsid_list: Report suite IDs
            element_list: Elements to get classifications for 
                         (e.g., ["trackingcode", "evar1", "prop1"])
        """
        logger.info(f"Getting classifications for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetClassifications", {
            "rsid_list": rsid_list,
            "element_list": element_list
        })
    
    def get_settings(self, rsid_list: List[str]) -> Optional[List[Dict]]:
        """
        Retrieve comprehensive report suite settings.
        Aggregates: eVars, props, events, classifications, custom calendar, etc.
        """
        logger.info(f"Getting comprehensive settings for: {rsid_list}")
        return self._call_14_api("ReportSuite.GetSettings", {
            "rsid_list": rsid_list,
            "locale": "en_US"
        })
    
    # =========================================================================
    # SAVE METHODS - Apply configurations to target report suites
    # =========================================================================
    
    def save_evars(self, rsid_list: List[str], evars: List[Dict]) -> bool:
        """Save eVar configurations to specified report suites"""
        logger.info(f"Saving {len(evars)} eVars to: {rsid_list}")
        result = self._call_14_api("ReportSuite.SaveEvars", {
            "rsid_list": rsid_list,
            "evars": evars
        })
        return result is True or result == "true" or result == True
    
    def save_props(self, rsid_list: List[str], props: List[Dict]) -> bool:
        """Save prop configurations to specified report suites"""
        logger.info(f"Saving {len(props)} props to: {rsid_list}")
        result = self._call_14_api("ReportSuite.SaveProps", {
            "rsid_list": rsid_list,
            "props": props
        })
        return result is True or result == "true" or result == True
    
    def save_events(self, rsid_list: List[str], events: List[Dict]) -> bool:
        """Save success event configurations to specified report suites"""
        logger.info(f"Saving {len(events)} events to: {rsid_list}")
        result = self._call_14_api("ReportSuite.SaveEvents", {
            "rsid_list": rsid_list,
            "events": events
        })
        return result is True or result == "true" or result == True
    
    def save_internal_url_filters(self, rsid_list: List[str], filters: List[str]) -> bool:
        """Save internal URL filter configurations"""
        logger.info(f"Saving {len(filters)} internal URL filters to: {rsid_list}")
        result = self._call_14_api("ReportSuite.SaveInternalURLFilters", {
            "rsid_list": rsid_list,
            "internal_url_filters": filters
        })
        return result is True or result == "true" or result == True
    
    def save_marketing_channels(self, rsid_list: List[str], channels: List[Dict]) -> bool:
        """Save marketing channel configurations"""
        logger.info(f"Saving {len(channels)} marketing channels to: {rsid_list}")
        result = self._call_14_api("ReportSuite.SaveMarketingChannels", {
            "rsid_list": rsid_list,
            "channels": channels
        })
        return result is True or result == "true" or result == True
    
    def save_marketing_channel_rules(self, rsid_list: List[str], rules: Dict) -> bool:
        """Save marketing channel rule configurations"""
        logger.info(f"Saving marketing channel rules to: {rsid_list}")
        result = self._call_14_api("ReportSuite.SaveMarketingChannelRules", {
            "rsid_list": rsid_list,
            "marketing_channel_rules": rules
        })
        return result is True or result == "true" or result == True
    
    def save_list_variables(self, rsid_list: List[str], list_vars: List[Dict]) -> bool:
        """Save list variable configurations"""
        logger.info(f"Saving list variables to: {rsid_list}")
        result = self._call_14_api("ReportSuite.SaveListVariables", {
            "rsid_list": rsid_list,
            "list_variables": list_vars
        })
        return result == 1 or result == "1" or result is True
    
    # =========================================================================
    # SYNC OPERATIONS
    # =========================================================================
    
    def _extract_config_data(self, api_response: List[Dict], key: str) -> Optional[List]:
        """Extract configuration data from API response"""
        if not api_response or len(api_response) == 0:
            return None
        return api_response[0].get(key, [])
    
    def sync_evars(self, target_rsids: List[str], dry_run: bool = False) -> Dict[str, Any]:
        """
        Sync eVar configurations from production to target report suites.
        
        Args:
            target_rsids: List of target report suite IDs
            dry_run: If True, only show what would be changed
            
        Returns:
            Dict with sync results
        """
        logger.info("=" * 60)
        logger.info("SYNCING eVars")
        logger.info("=" * 60)
        
        # Get source configuration
        source_data = self.get_evars([self.rs_config.production_rsid])
        if not source_data:
            return {"success": False, "error": "Failed to get source eVars"}
        
        evars = self._extract_config_data(source_data, "evars")
        if not evars:
            return {"success": False, "error": "No eVars found in source"}
        
        # Count enabled eVars
        enabled_evars = [e for e in evars if e.get("enabled")]
        logger.info(f"Found {len(evars)} total eVars, {len(enabled_evars)} enabled")
        
        if dry_run:
            logger.info("[DRY RUN] Would sync the following eVars:")
            for evar in enabled_evars[:10]:  # Show first 10
                logger.info(f"  - {evar.get('id')}: {evar.get('name')} "
                           f"(type: {evar.get('type')}, expiration: {evar.get('expiration_type')})")
            if len(enabled_evars) > 10:
                logger.info(f"  ... and {len(enabled_evars) - 10} more")
            return {"success": True, "dry_run": True, "evar_count": len(evars)}
        
        # Apply to targets
        success = self.save_evars(target_rsids, evars)
        
        result = {
            "success": success,
            "config_type": "evars",
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "total_count": len(evars),
            "enabled_count": len(enabled_evars)
        }
        
        self.sync_results["evars"] = result
        return result
    
    def sync_props(self, target_rsids: List[str], dry_run: bool = False) -> Dict[str, Any]:
        """Sync prop (traffic variable) configurations"""
        logger.info("=" * 60)
        logger.info("SYNCING Props (Traffic Variables)")
        logger.info("=" * 60)
        
        source_data = self.get_props([self.rs_config.production_rsid])
        if not source_data:
            return {"success": False, "error": "Failed to get source props"}
        
        props = self._extract_config_data(source_data, "props")
        if not props:
            return {"success": False, "error": "No props found in source"}
        
        enabled_props = [p for p in props if p.get("enabled")]
        logger.info(f"Found {len(props)} total props, {len(enabled_props)} enabled")
        
        if dry_run:
            logger.info("[DRY RUN] Would sync the following props:")
            for prop in enabled_props[:10]:
                logger.info(f"  - {prop.get('id')}: {prop.get('name')} "
                           f"(pathing: {prop.get('pathing_enabled')}, list: {prop.get('list_enabled')})")
            if len(enabled_props) > 10:
                logger.info(f"  ... and {len(enabled_props) - 10} more")
            return {"success": True, "dry_run": True, "prop_count": len(props)}
        
        success = self.save_props(target_rsids, props)
        
        result = {
            "success": success,
            "config_type": "props",
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "total_count": len(props),
            "enabled_count": len(enabled_props)
        }
        
        self.sync_results["props"] = result
        return result
    
    def sync_events(self, target_rsids: List[str], dry_run: bool = False) -> Dict[str, Any]:
        """Sync success event configurations"""
        logger.info("=" * 60)
        logger.info("SYNCING Success Events")
        logger.info("=" * 60)
        
        source_data = self.get_events([self.rs_config.production_rsid])
        if not source_data:
            return {"success": False, "error": "Failed to get source events"}
        
        events = self._extract_config_data(source_data, "events")
        if not events:
            return {"success": False, "error": "No events found in source"}
        
        # Filter to custom events (event1-event1000)
        custom_events = [e for e in events if e.get("id", "").startswith("event")]
        logger.info(f"Found {len(events)} total events, {len(custom_events)} custom events")
        
        if dry_run:
            logger.info("[DRY RUN] Would sync the following events:")
            for event in custom_events[:10]:
                logger.info(f"  - {event.get('id')}: {event.get('name')} "
                           f"(type: {event.get('type')}, serialization: {event.get('serialization')})")
            if len(custom_events) > 10:
                logger.info(f"  ... and {len(custom_events) - 10} more")
            return {"success": True, "dry_run": True, "event_count": len(events)}
        
        success = self.save_events(target_rsids, events)
        
        result = {
            "success": success,
            "config_type": "events",
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "total_count": len(events),
            "custom_count": len(custom_events)
        }
        
        self.sync_results["events"] = result
        return result
    
    def sync_internal_url_filters(self, target_rsids: List[str], dry_run: bool = False) -> Dict[str, Any]:
        """Sync internal URL filter configurations"""
        logger.info("=" * 60)
        logger.info("SYNCING Internal URL Filters")
        logger.info("=" * 60)
        
        source_data = self.get_internal_url_filters([self.rs_config.production_rsid])
        if not source_data:
            return {"success": False, "error": "Failed to get source internal URL filters"}
        
        filters = self._extract_config_data(source_data, "internal_url_filters")
        if not filters:
            logger.warning("No internal URL filters found in source")
            return {"success": True, "warning": "No filters to sync", "filter_count": 0}
        
        logger.info(f"Found {len(filters)} internal URL filters")
        
        if dry_run:
            logger.info("[DRY RUN] Would sync the following filters:")
            for f in filters[:10]:
                logger.info(f"  - {f}")
            if len(filters) > 10:
                logger.info(f"  ... and {len(filters) - 10} more")
            return {"success": True, "dry_run": True, "filter_count": len(filters)}
        
        success = self.save_internal_url_filters(target_rsids, filters)
        
        result = {
            "success": success,
            "config_type": "internal_url_filters",
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "filter_count": len(filters)
        }
        
        self.sync_results["internal_url_filters"] = result
        return result
    
    def sync_marketing_channels(self, target_rsids: List[str], dry_run: bool = False) -> Dict[str, Any]:
        """Sync marketing channel configurations"""
        logger.info("=" * 60)
        logger.info("SYNCING Marketing Channels")
        logger.info("=" * 60)
        
        source_data = self.get_marketing_channels([self.rs_config.production_rsid])
        if not source_data:
            return {"success": False, "error": "Failed to get source marketing channels"}
        
        channels = self._extract_config_data(source_data, "marketing_channels")
        if not channels:
            logger.warning("No marketing channels found in source")
            return {"success": True, "warning": "No channels to sync", "channel_count": 0}
        
        logger.info(f"Found {len(channels)} marketing channels")
        
        if dry_run:
            logger.info("[DRY RUN] Would sync the following channels:")
            for ch in channels:
                logger.info(f"  - {ch.get('name')} (id: {ch.get('id')}, enabled: {ch.get('enabled')})")
            return {"success": True, "dry_run": True, "channel_count": len(channels)}
        
        success = self.save_marketing_channels(target_rsids, channels)
        
        result = {
            "success": success,
            "config_type": "marketing_channels",
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "channel_count": len(channels)
        }
        
        self.sync_results["marketing_channels"] = result
        return result
    
    def sync_all(self, target_rsids: List[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        Perform a full synchronization of all configuration types.
        
        Args:
            target_rsids: List of target report suite IDs (defaults to config targets)
            dry_run: If True, only show what would be changed
            
        Returns:
            Summary of all sync operations
        """
        if target_rsids is None:
            target_rsids = self.rs_config.target_rsids
            
        logger.info("#" * 60)
        logger.info("STARTING FULL REPORT SUITE SYNC")
        logger.info(f"Source: {self.rs_config.production_rsid}")
        logger.info(f"Targets: {target_rsids}")
        logger.info(f"Dry Run: {dry_run}")
        logger.info("#" * 60)
        
        results = {}
        
        # Sync each configuration type
        results["evars"] = self.sync_evars(target_rsids, dry_run)
        results["props"] = self.sync_props(target_rsids, dry_run)
        results["events"] = self.sync_events(target_rsids, dry_run)
        results["internal_url_filters"] = self.sync_internal_url_filters(target_rsids, dry_run)
        results["marketing_channels"] = self.sync_marketing_channels(target_rsids, dry_run)
        
        # Summarize results
        successful = sum(1 for r in results.values() if r.get("success"))
        failed = len(results) - successful
        
        summary = {
            "timestamp": datetime.now().isoformat(),
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "dry_run": dry_run,
            "total_operations": len(results),
            "successful": successful,
            "failed": failed,
            "details": results
        }
        
        logger.info("#" * 60)
        logger.info("SYNC COMPLETE")
        logger.info(f"Successful: {successful}/{len(results)}")
        logger.info(f"Failed: {failed}/{len(results)}")
        logger.info("#" * 60)
        
        return summary
    
    # =========================================================================
    # COMPARISON & BACKUP
    # =========================================================================
    
    def compare_report_suites(self, rsid1: str, rsid2: str) -> Dict[str, Any]:
        """
        Compare configurations between two report suites.
        Useful for identifying differences before syncing.
        """
        logger.info(f"Comparing {rsid1} vs {rsid2}")
        
        comparison = {"rsid1": rsid1, "rsid2": rsid2, "differences": {}}
        
        # Compare eVars
        evars1 = self.get_evars([rsid1])
        evars2 = self.get_evars([rsid2])
        
        if evars1 and evars2:
            evars1_data = self._extract_config_data(evars1, "evars") or []
            evars2_data = self._extract_config_data(evars2, "evars") or []
            
            evars1_enabled = {str(e["id"]): e.get("name") for e in evars1_data if e.get("enabled")}
            evars2_enabled = {str(e["id"]): e.get("name") for e in evars2_data if e.get("enabled")}
            
            comparison["differences"]["evars"] = {
                f"{rsid1}_enabled": len(evars1_enabled),
                f"{rsid2}_enabled": len(evars2_enabled),
                "only_in_first": {k: evars1_enabled[k] for k in set(evars1_enabled) - set(evars2_enabled)},
                "only_in_second": {k: evars2_enabled[k] for k in set(evars2_enabled) - set(evars1_enabled)}
            }
        
        # Compare props
        props1 = self.get_props([rsid1])
        props2 = self.get_props([rsid2])
        
        if props1 and props2:
            props1_data = self._extract_config_data(props1, "props") or []
            props2_data = self._extract_config_data(props2, "props") or []
            
            props1_enabled = {str(p["id"]): p.get("name") for p in props1_data if p.get("enabled")}
            props2_enabled = {str(p["id"]): p.get("name") for p in props2_data if p.get("enabled")}
            
            comparison["differences"]["props"] = {
                f"{rsid1}_enabled": len(props1_enabled),
                f"{rsid2}_enabled": len(props2_enabled),
                "only_in_first": {k: props1_enabled[k] for k in set(props1_enabled) - set(props2_enabled)},
                "only_in_second": {k: props2_enabled[k] for k in set(props2_enabled) - set(props1_enabled)}
            }
        
        # Compare events
        events1 = self.get_events([rsid1])
        events2 = self.get_events([rsid2])
        
        if events1 and events2:
            events1_data = self._extract_config_data(events1, "events") or []
            events2_data = self._extract_config_data(events2, "events") or []
            
            # Filter to custom events with names
            custom1 = {e["id"]: e.get("name") for e in events1_data 
                      if e.get("id", "").startswith("event") and e.get("name")}
            custom2 = {e["id"]: e.get("name") for e in events2_data 
                      if e.get("id", "").startswith("event") and e.get("name")}
            
            comparison["differences"]["events"] = {
                f"{rsid1}_custom": len(custom1),
                f"{rsid2}_custom": len(custom2),
                "only_in_first": {k: custom1[k] for k in set(custom1) - set(custom2)},
                "only_in_second": {k: custom2[k] for k in set(custom2) - set(custom1)}
            }
        
        return comparison
    
    def backup_report_suite(self, rsid: str, output_file: str = None) -> Dict[str, Any]:
        """
        Create a full backup of a report suite's configuration.
        
        Args:
            rsid: Report suite ID to backup
            output_file: Optional file path to save backup JSON
            
        Returns:
            Dict containing all configuration data
        """
        if output_file is None:
            output_file = f"backup_{rsid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
        logger.info(f"Creating backup of {rsid}...")
        
        backup = {
            "rsid": rsid,
            "backup_timestamp": datetime.now().isoformat(),
            "company_name": self.company_name,
            "configurations": {}
        }
        
        # Backup each configuration type
        configs_to_backup = [
            ("evars", lambda: self.get_evars([rsid])),
            ("props", lambda: self.get_props([rsid])),
            ("events", lambda: self.get_events([rsid])),
            ("internal_url_filters", lambda: self.get_internal_url_filters([rsid])),
            ("marketing_channels", lambda: self.get_marketing_channels([rsid])),
            ("list_variables", lambda: self.get_list_variables([rsid])),
        ]
        
        for config_name, get_func in configs_to_backup:
            try:
                data = get_func()
                if data and len(data) > 0:
                    backup["configurations"][config_name] = data[0]
                    logger.info(f"  ✓ {config_name}")
                else:
                    logger.warning(f"  ⚠ {config_name} - no data returned")
            except Exception as e:
                logger.error(f"  ✗ {config_name} - error: {str(e)}")
        
        # Save to file
        with open(output_file, 'w') as f:
            json.dump(backup, f, indent=2)
        
        logger.info(f"Backup saved to: {output_file}")
        return backup
    
    def restore_from_backup(self, backup_file: str, target_rsids: List[str], 
                           configs_to_restore: List[str] = None) -> Dict[str, Any]:
        """
        Restore configurations from a backup file.
        
        Args:
            backup_file: Path to backup JSON file
            target_rsids: Report suites to restore to
            configs_to_restore: Optional list of specific configs to restore
                               (e.g., ["evars", "props"])
        """
        logger.info(f"Restoring from {backup_file} to {target_rsids}")
        
        with open(backup_file, 'r') as f:
            backup = json.load(f)
        
        results = {}
        configs = backup.get("configurations", {})
        
        if configs_to_restore:
            configs = {k: v for k, v in configs.items() if k in configs_to_restore}
        
        # Map config names to save functions
        save_map = {
            "evars": lambda data: self.save_evars(target_rsids, data.get("evars", [])),
            "props": lambda data: self.save_props(target_rsids, data.get("props", [])),
            "events": lambda data: self.save_events(target_rsids, data.get("events", [])),
            "internal_url_filters": lambda data: self.save_internal_url_filters(
                target_rsids, data.get("internal_url_filters", [])
            ),
            "marketing_channels": lambda data: self.save_marketing_channels(
                target_rsids, data.get("channels", [])
            ),
        }
        
        for config_name, config_data in configs.items():
            if config_name in save_map:
                try:
                    success = save_map[config_name](config_data)
                    results[config_name] = {"success": success}
                    status = "✓" if success else "✗"
                    logger.info(f"  {status} {config_name}")
                except Exception as e:
                    results[config_name] = {"success": False, "error": str(e)}
                    logger.error(f"  ✗ {config_name} - {str(e)}")
        
        return results


# =============================================================================
# 2.0 API UTILITIES (for reference/comparison)
# =============================================================================

def list_dimensions_20(analytics_client: api2.Analytics, rsid: str) -> None:
    """
    List available dimensions using the 2.0 API.
    Useful for comparing with 1.4 API results.
    """
    logger.info(f"Listing dimensions for {rsid} via 2.0 API...")
    
    try:
        dims = analytics_client.getDimensions(rsid=rsid)
        if dims is not None and not dims.empty:
            # Filter to eVars and props
            evars = dims[dims['id'].str.contains('variables/evar', na=False)]
            props = dims[dims['id'].str.contains('variables/prop', na=False)]
            
            logger.info(f"Found {len(evars)} eVars and {len(props)} props via 2.0 API")
    except Exception as e:
        logger.error(f"Failed to get dimensions: {str(e)}")


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    """Main execution function demonstrating the sync workflow"""
    
    print("\n" + "=" * 60)
    print("ADOBE ANALYTICS REPORT SUITE SYNC TOOL")
    print("Using aanalytics2 package")
    print("=" * 60)
    
    # Step 1: Load OAuth credentials (from env vars or config file)
    oauth_config = OAuthConfig()
    config_file = get_or_create_config_file(oauth_config)
    
    if config_file is None:
        print("\n⚠️  No OAuth credentials found!")
        print("\n   Option 1: Set environment variables (recommended)")
        print("   -------------------------------------------------")
        print("   Create a .env file with:")
        print("     AA_ORG_ID=YOUR_ORG_ID@AdobeOrg")
        print("     AA_CLIENT_ID=your_client_id")
        print("     AA_CLIENT_SECRET=your_client_secret")
        print("     AA_PRODUCTION_RSID=your_prod_rsid")
        print("     AA_DEV_RSID=your_dev_rsid")
        print("     AA_STAGING_RSID=your_staging_rsid")
        print("\n   Option 2: Use a JSON config file")
        print("   ---------------------------------")
        sample_file = "config_analytics_oauth.json"
        create_sample_config_file(sample_file)
        print(f"   Sample created: {sample_file}")
        print("   Update it with your credentials and re-run.")
        return
    
    # Step 2: Initialize report suite configuration (reads from env vars)
    rs_config = ReportSuiteConfig()
    
    print(f"\nConfiguration:")
    print(f"  OAuth: {'Environment variables' if oauth_config.is_configured() else 'Config file'}")
    print(f"  Source (Production): {rs_config.production_rsid}")
    print(f"  Target (Dev):        {rs_config.dev_rsid}")
    print(f"  Target (Staging):    {rs_config.staging_rsid}")
    
    # Warn if using default dummy values
    if rs_config.is_using_defaults():
        print("\n⚠️  WARNING: Using default dummy report suite IDs!")
        print("   Add to your .env file:")
        print("     AA_PRODUCTION_RSID=your_prod_rsid")
        print("     AA_DEV_RSID=your_dev_rsid")
        print("     AA_STAGING_RSID=your_staging_rsid")
        return
    
    # Step 3: Create synchronizer and connect
    synchronizer = ReportSuiteSynchronizer(config_file, rs_config)
    
    print("\nConnecting to Adobe Analytics...")
    if not synchronizer.connect():
        print("❌ Connection failed. Check your credentials.")
        return
    
    print(f"✓ Connected to: {synchronizer.company_name}")
    
    # Step 4: Create backup of dev report suite first
    print("\n" + "-" * 60)
    print("STEP 1: Creating backup of dev report suite...")
    print("-" * 60)
    backup = synchronizer.backup_report_suite(rs_config.dev_rsid)
    
    # Step 5: Compare production vs dev
    print("\n" + "-" * 60)
    print("STEP 2: Comparing production vs dev report suites...")
    print("-" * 60)
    comparison = synchronizer.compare_report_suites(
        rs_config.production_rsid,
        rs_config.dev_rsid
    )
    print(json.dumps(comparison, indent=2))
    
    # Step 6: Perform dry run
    print("\n" + "-" * 60)
    print("STEP 3: Performing dry run sync...")
    print("-" * 60)
    dry_run_results = synchronizer.sync_all(dry_run=True)
    
    # Step 7: Prompt for actual sync (in production, you'd want proper confirmation)
    print("\n" + "-" * 60)
    print("STEP 4: Ready for actual sync")
    print("-" * 60)
    print("\nTo perform the actual sync, uncomment the following line:")
    print("  # sync_results = synchronizer.sync_all(dry_run=False)")
    
    # Uncomment to perform actual sync:
    # print("\nPerforming actual sync...")
    # sync_results = synchronizer.sync_all(dry_run=False)
    # print(json.dumps(sync_results, indent=2))
    
    print("\n" + "=" * 60)
    print("WORKFLOW COMPLETE")
    print("=" * 60)
    print("\nSummary of actions taken:")
    print("  1. ✓ Connected to Adobe Analytics")
    print("  2. ✓ Created backup of dev report suite")
    print("  3. ✓ Compared production vs dev configurations")
    print("  4. ✓ Performed dry run sync")
    print("  5. ⏸ Actual sync ready (uncomment to execute)")
    
    # Clean up temp config file if we created one
    temp_config = ".aa_config_from_env.json"
    if Path(temp_config).exists() and oauth_config.is_configured():
        Path(temp_config).unlink()


if __name__ == "__main__":
    main()