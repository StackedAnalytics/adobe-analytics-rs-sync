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
Version: 1.2

Changelog:
  v1.2 - Added sync scope control and change detection
         - include_disabled parameter to control sync scope
         - sync_changed_only parameter for efficient change detection
         - SyncConfig dataclass for reusable configurations
         - Fixed bug where dry_run showed enabled-only but synced all
  v1.1 - Initial OAuth support and environment variable configuration
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


@dataclass
class SyncConfig:
    """
    Configuration options for report suite synchronization.

    This dataclass groups sync parameters for cleaner API usage when
    using multiple options together.

    Attributes:
        dry_run: If True, only preview changes without applying them
        include_disabled: If True, sync all variables (including disabled).
                         If False (default), only sync enabled variables.
        sync_changed_only: If True, compare source vs target and only sync
                          variables that have changed or are new.
                          If False (default), sync all filtered variables.

    Examples:
        # Create a config for safe, efficient syncing
        config = SyncConfig(
            dry_run=True,
            include_disabled=False,
            sync_changed_only=True
        )

        # Reuse config across multiple operations
        sync.sync_evars(["dev_rsid"], config=config)
        sync.sync_props(["dev_rsid"], config=config)
    """
    dry_run: bool = False
    include_disabled: bool = False
    sync_changed_only: bool = False


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

    def _compare_variable_configs(
        self,
        var1: Dict[str, Any],
        var2: Dict[str, Any],
        exclude_keys: Optional[List[str]] = None
    ) -> bool:
        """
        Deep comparison of two variable configurations.

        Compares all dictionary keys and values to determine if two variable
        configurations are identical. Excludes certain keys that are expected
        to differ between source and target (like rsid).

        Args:
            var1: First variable configuration dict
            var2: Second variable configuration dict
            exclude_keys: Keys to ignore in comparison (defaults to ['rsid'])

        Returns:
            True if configurations are identical, False if different

        Examples:
            # Same configuration
            v1 = {"id": "evar1", "name": "Campaign", "enabled": True}
            v2 = {"id": "evar1", "name": "Campaign", "enabled": True}
            assert self._compare_variable_configs(v1, v2) == True

            # Different configuration
            v1 = {"id": "evar1", "name": "Campaign", "enabled": True}
            v2 = {"id": "evar1", "name": "Campaign", "enabled": False}
            assert self._compare_variable_configs(v1, v2) == False
        """
        if exclude_keys is None:
            exclude_keys = ['rsid']  # rsid differs between source/target

        # Get all keys from both dicts, excluding specified keys
        keys1 = set(var1.keys()) - set(exclude_keys)
        keys2 = set(var2.keys()) - set(exclude_keys)

        # If different keys, they're different
        if keys1 != keys2:
            return False

        # Compare all values
        for key in keys1:
            if var1.get(key) != var2.get(key):
                return False

        return True

    def _filter_variables_to_sync(
        self,
        source_vars: List[Dict],
        target_vars: Optional[List[Dict]],
        include_disabled: bool,
        sync_changed_only: bool,
        var_type: str  # For logging: "eVar", "prop", "event"
    ) -> tuple[List[Dict], Dict[str, int]]:
        """
        Filter variables based on enabled status and change detection.

        This method applies a two-step filtering process:
        1. Filter by enabled status (if include_disabled=False)
        2. Filter by changes (if sync_changed_only=True)

        Args:
            source_vars: Variables from source report suite
            target_vars: Variables from target report suite (None if not comparing)
            include_disabled: Whether to include disabled variables
            sync_changed_only: Whether to only sync changed variables
            var_type: Type of variable for logging (eVar/prop/event)

        Returns:
            Tuple of (filtered_variables_to_sync, statistics_dict)

            statistics_dict contains:
            - total_source: Total variables in source
            - enabled_source: Number of enabled variables in source
            - disabled_source: Number of disabled variables in source
            - to_sync: Number of variables that will be synced
            - unchanged: Number of unchanged variables (if comparing)
            - changed: Number of changed variables (if comparing)
            - new: Number of new variables (if comparing)
        """
        stats = {
            "total_source": len(source_vars),
            "enabled_source": 0,
            "disabled_source": 0,
            "to_sync": 0,
            "unchanged": 0,
            "changed": 0,
            "new": 0
        }

        # Step 1: Filter by enabled status
        if include_disabled:
            filtered = source_vars.copy()
        else:
            # Filter to only enabled (handle events which may not have 'enabled' field)
            filtered = [v for v in source_vars if v.get("enabled", True)]

        stats["enabled_source"] = len([v for v in source_vars if v.get("enabled", True)])
        stats["disabled_source"] = stats["total_source"] - stats["enabled_source"]

        # Step 2: Filter by changes (if requested)
        if sync_changed_only and target_vars:
            # Create lookup dict by ID
            target_lookup = {v.get("id"): v for v in target_vars}

            vars_to_sync = []
            for source_var in filtered:
                var_id = source_var.get("id")
                target_var = target_lookup.get(var_id)

                if target_var is None:
                    # Variable doesn't exist in target - include it
                    vars_to_sync.append(source_var)
                    stats["new"] += 1
                elif not self._compare_variable_configs(source_var, target_var):
                    # Variable exists but has changes - include it
                    vars_to_sync.append(source_var)
                    stats["changed"] += 1
                else:
                    # Variable unchanged - skip it
                    stats["unchanged"] += 1

            filtered = vars_to_sync

        stats["to_sync"] = len(filtered)

        return filtered, stats
    
    def sync_evars(
        self,
        target_rsids: List[str],
        dry_run: bool = False,
        include_disabled: bool = False,
        sync_changed_only: bool = False,
        config: Optional[SyncConfig] = None
    ) -> Dict[str, Any]:
        """
        Sync eVar configurations from production to target report suites.

        Args:
            target_rsids: List of target report suite IDs
            dry_run: If True, only show what would be changed
            include_disabled: If True, sync all variables (including disabled).
                            If False (default), only sync enabled variables.
            sync_changed_only: If True, compare source vs target and only sync
                             variables that have changed or are new.
                             If False (default), sync all filtered variables.
            config: Optional SyncConfig object (overrides individual parameters)

        Returns:
            Dict with sync results including statistics

        Examples:
            # Sync only enabled variables (default, safest)
            sync.sync_evars(["dev_rsid"])

            # Sync all variables including disabled
            sync.sync_evars(["dev_rsid"], include_disabled=True)

            # Sync only changed enabled variables (efficient)
            sync.sync_evars(["dev_rsid"], sync_changed_only=True)

            # Use config object for complex cases
            config = SyncConfig(include_disabled=True, sync_changed_only=True)
            sync.sync_evars(["dev_rsid"], config=config)
        """
        # If config provided, use its values (overrides individual params)
        if config:
            dry_run = config.dry_run
            include_disabled = config.include_disabled
            sync_changed_only = config.sync_changed_only

        logger.info("=" * 60)
        logger.info("SYNCING eVars")
        logger.info("=" * 60)

        # Get source configuration
        source_data = self.get_evars([self.rs_config.production_rsid])
        if not source_data:
            return {"success": False, "error": "Failed to get source eVars"}

        source_evars = self._extract_config_data(source_data, "evars")
        if not source_evars:
            return {"success": False, "error": "No eVars found in source"}

        # Get target configuration if comparing changes
        target_evars = None
        if sync_changed_only:
            logger.info(f"Fetching target eVars for comparison from {target_rsids[0]}...")
            target_data = self.get_evars([target_rsids[0]])
            if target_data:
                target_evars = self._extract_config_data(target_data, "evars")
            else:
                logger.warning("Failed to fetch target eVars; will sync all filtered variables")

        # Filter variables based on parameters
        evars_to_sync, stats = self._filter_variables_to_sync(
            source_evars,
            target_evars,
            include_disabled,
            sync_changed_only,
            "eVar"
        )

        # Log filtering results
        logger.info(f"Source: {stats['total_source']} total eVars "
                   f"({stats['enabled_source']} enabled, {stats['disabled_source']} disabled)")
        logger.info(f"Filtering: include_disabled={include_disabled}, "
                   f"sync_changed_only={sync_changed_only}")

        if sync_changed_only and target_evars:
            logger.info(f"Change detection: {stats['new']} new, {stats['changed']} changed, "
                       f"{stats['unchanged']} unchanged")

        logger.info(f"Will sync: {stats['to_sync']} eVars")

        if dry_run:
            logger.info("[DRY RUN] Would sync the following eVars:")
            for evar in evars_to_sync[:10]:  # Show first 10
                status = ""
                if sync_changed_only and target_evars:
                    target_lookup = {v.get("id"): v for v in target_evars}
                    if evar.get("id") not in target_lookup:
                        status = " [NEW]"
                    elif not self._compare_variable_configs(evar, target_lookup[evar.get("id")]):
                        status = " [CHANGED]"

                logger.info(f"  - {evar.get('id')}: {evar.get('name')} "
                           f"(enabled: {evar.get('enabled')}, type: {evar.get('type')}, "
                           f"expiration: {evar.get('expiration_type')}){status}")
            if len(evars_to_sync) > 10:
                logger.info(f"  ... and {len(evars_to_sync) - 10} more")

            return {
                "success": True,
                "dry_run": True,
                "config_type": "evars",
                "stats": stats
            }

        # If no variables to sync, return success
        if not evars_to_sync:
            logger.info("No eVars to sync (all filtered out or unchanged)")
            return {
                "success": True,
                "config_type": "evars",
                "source_rsid": self.rs_config.production_rsid,
                "target_rsids": target_rsids,
                "stats": stats
            }

        # Apply to targets (BUG FIX: use filtered list instead of all evars)
        success = self.save_evars(target_rsids, evars_to_sync)

        result = {
            "success": success,
            "config_type": "evars",
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "stats": stats
        }

        self.sync_results["evars"] = result
        return result
    
    def sync_props(
        self,
        target_rsids: List[str],
        dry_run: bool = False,
        include_disabled: bool = False,
        sync_changed_only: bool = False,
        config: Optional[SyncConfig] = None
    ) -> Dict[str, Any]:
        """
        Sync prop (traffic variable) configurations.

        Args:
            target_rsids: List of target report suite IDs
            dry_run: If True, only show what would be changed
            include_disabled: If True, sync all variables (including disabled).
                            If False (default), only sync enabled variables.
            sync_changed_only: If True, compare source vs target and only sync
                             variables that have changed or are new.
                             If False (default), sync all filtered variables.
            config: Optional SyncConfig object (overrides individual parameters)

        Returns:
            Dict with sync results including statistics
        """
        # If config provided, use its values (overrides individual params)
        if config:
            dry_run = config.dry_run
            include_disabled = config.include_disabled
            sync_changed_only = config.sync_changed_only

        logger.info("=" * 60)
        logger.info("SYNCING Props (Traffic Variables)")
        logger.info("=" * 60)

        # Get source configuration
        source_data = self.get_props([self.rs_config.production_rsid])
        if not source_data:
            return {"success": False, "error": "Failed to get source props"}

        source_props = self._extract_config_data(source_data, "props")
        if not source_props:
            return {"success": False, "error": "No props found in source"}

        # Get target configuration if comparing changes
        target_props = None
        if sync_changed_only:
            logger.info(f"Fetching target props for comparison from {target_rsids[0]}...")
            target_data = self.get_props([target_rsids[0]])
            if target_data:
                target_props = self._extract_config_data(target_data, "props")
            else:
                logger.warning("Failed to fetch target props; will sync all filtered variables")

        # Filter variables based on parameters
        props_to_sync, stats = self._filter_variables_to_sync(
            source_props,
            target_props,
            include_disabled,
            sync_changed_only,
            "prop"
        )

        # Log filtering results
        logger.info(f"Source: {stats['total_source']} total props "
                   f"({stats['enabled_source']} enabled, {stats['disabled_source']} disabled)")
        logger.info(f"Filtering: include_disabled={include_disabled}, "
                   f"sync_changed_only={sync_changed_only}")

        if sync_changed_only and target_props:
            logger.info(f"Change detection: {stats['new']} new, {stats['changed']} changed, "
                       f"{stats['unchanged']} unchanged")

        logger.info(f"Will sync: {stats['to_sync']} props")

        if dry_run:
            logger.info("[DRY RUN] Would sync the following props:")
            for prop in props_to_sync[:10]:  # Show first 10
                status = ""
                if sync_changed_only and target_props:
                    target_lookup = {v.get("id"): v for v in target_props}
                    if prop.get("id") not in target_lookup:
                        status = " [NEW]"
                    elif not self._compare_variable_configs(prop, target_lookup[prop.get("id")]):
                        status = " [CHANGED]"

                logger.info(f"  - {prop.get('id')}: {prop.get('name')} "
                           f"(enabled: {prop.get('enabled')}, pathing: {prop.get('pathing_enabled')}, "
                           f"list: {prop.get('list_enabled')}){status}")
            if len(props_to_sync) > 10:
                logger.info(f"  ... and {len(props_to_sync) - 10} more")

            return {
                "success": True,
                "dry_run": True,
                "config_type": "props",
                "stats": stats
            }

        # If no variables to sync, return success
        if not props_to_sync:
            logger.info("No props to sync (all filtered out or unchanged)")
            return {
                "success": True,
                "config_type": "props",
                "source_rsid": self.rs_config.production_rsid,
                "target_rsids": target_rsids,
                "stats": stats
            }

        # Apply to targets (BUG FIX: use filtered list instead of all props)
        success = self.save_props(target_rsids, props_to_sync)

        result = {
            "success": success,
            "config_type": "props",
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "stats": stats
        }

        self.sync_results["props"] = result
        return result
    
    def sync_events(
        self,
        target_rsids: List[str],
        dry_run: bool = False,
        include_disabled: bool = False,
        sync_changed_only: bool = False,
        config: Optional[SyncConfig] = None
    ) -> Dict[str, Any]:
        """
        Sync success event configurations.

        Note: Events typically don't have an 'enabled' field, so they're
        treated as enabled by default. The include_disabled parameter is
        included for API consistency.

        Args:
            target_rsids: List of target report suite IDs
            dry_run: If True, only show what would be changed
            include_disabled: If True, sync all variables (including disabled).
                            If False (default), only sync enabled variables.
                            Note: Events don't typically have 'enabled' field.
            sync_changed_only: If True, compare source vs target and only sync
                             variables that have changed or are new.
                             If False (default), sync all filtered variables.
            config: Optional SyncConfig object (overrides individual parameters)

        Returns:
            Dict with sync results including statistics
        """
        # If config provided, use its values (overrides individual params)
        if config:
            dry_run = config.dry_run
            include_disabled = config.include_disabled
            sync_changed_only = config.sync_changed_only

        logger.info("=" * 60)
        logger.info("SYNCING Success Events")
        logger.info("=" * 60)

        # Get source configuration
        source_data = self.get_events([self.rs_config.production_rsid])
        if not source_data:
            return {"success": False, "error": "Failed to get source events"}

        source_events = self._extract_config_data(source_data, "events")
        if not source_events:
            return {"success": False, "error": "No events found in source"}

        # Get target configuration if comparing changes
        target_events = None
        if sync_changed_only:
            logger.info(f"Fetching target events for comparison from {target_rsids[0]}...")
            target_data = self.get_events([target_rsids[0]])
            if target_data:
                target_events = self._extract_config_data(target_data, "events")
            else:
                logger.warning("Failed to fetch target events; will sync all filtered variables")

        # Filter variables based on parameters
        # Note: Events don't have 'enabled' field, so v.get("enabled", True) treats them as enabled
        events_to_sync, stats = self._filter_variables_to_sync(
            source_events,
            target_events,
            include_disabled,
            sync_changed_only,
            "event"
        )

        # Count custom events for logging
        custom_count = len([e for e in events_to_sync if e.get("id", "").startswith("event")])

        # Log filtering results
        logger.info(f"Source: {stats['total_source']} total events "
                   f"({stats['enabled_source']} enabled, {stats['disabled_source']} disabled)")
        logger.info(f"Filtering: include_disabled={include_disabled}, "
                   f"sync_changed_only={sync_changed_only}")

        if sync_changed_only and target_events:
            logger.info(f"Change detection: {stats['new']} new, {stats['changed']} changed, "
                       f"{stats['unchanged']} unchanged")

        logger.info(f"Will sync: {stats['to_sync']} events ({custom_count} custom)")

        if dry_run:
            logger.info("[DRY RUN] Would sync the following events:")
            for event in events_to_sync[:10]:  # Show first 10
                status = ""
                if sync_changed_only and target_events:
                    target_lookup = {v.get("id"): v for v in target_events}
                    if event.get("id") not in target_lookup:
                        status = " [NEW]"
                    elif not self._compare_variable_configs(event, target_lookup[event.get("id")]):
                        status = " [CHANGED]"

                logger.info(f"  - {event.get('id')}: {event.get('name')} "
                           f"(type: {event.get('type')}, serialization: {event.get('serialization')}){status}")
            if len(events_to_sync) > 10:
                logger.info(f"  ... and {len(events_to_sync) - 10} more")

            return {
                "success": True,
                "dry_run": True,
                "config_type": "events",
                "stats": stats
            }

        # If no variables to sync, return success
        if not events_to_sync:
            logger.info("No events to sync (all filtered out or unchanged)")
            return {
                "success": True,
                "config_type": "events",
                "source_rsid": self.rs_config.production_rsid,
                "target_rsids": target_rsids,
                "stats": stats
            }

        # Apply to targets (BUG FIX: use filtered list instead of all events)
        success = self.save_events(target_rsids, events_to_sync)

        result = {
            "success": success,
            "config_type": "events",
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "stats": stats,
            "custom_count": custom_count
        }

        self.sync_results["events"] = result
        return result
    
    def sync_internal_url_filters(
        self,
        target_rsids: List[str],
        dry_run: bool = False,
        config: Optional[SyncConfig] = None
    ) -> Dict[str, Any]:
        """
        Sync internal URL filter configurations.

        Note: Internal URL filters don't have enabled/disabled status,
        so include_disabled and sync_changed_only parameters don't apply here.

        Args:
            target_rsids: List of target report suite IDs
            dry_run: If True, only show what would be changed
            config: Optional SyncConfig object (only dry_run is used)

        Returns:
            Dict with sync results
        """
        # If config provided, use dry_run value
        if config:
            dry_run = config.dry_run

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
    
    def sync_marketing_channels(
        self,
        target_rsids: List[str],
        dry_run: bool = False,
        config: Optional[SyncConfig] = None
    ) -> Dict[str, Any]:
        """
        Sync marketing channel configurations.

        Note: Marketing channels have an 'enabled' field but filtering
        logic is not currently implemented. All channels are synced.

        Args:
            target_rsids: List of target report suite IDs
            dry_run: If True, only show what would be changed
            config: Optional SyncConfig object (only dry_run is used)

        Returns:
            Dict with sync results
        """
        # If config provided, use dry_run value
        if config:
            dry_run = config.dry_run

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
    
    def sync_all(
        self,
        target_rsids: List[str] = None,
        dry_run: bool = False,
        include_disabled: bool = False,
        sync_changed_only: bool = False,
        config: Optional[SyncConfig] = None
    ) -> Dict[str, Any]:
        """
        Perform a full synchronization of all configuration types.

        Args:
            target_rsids: List of target report suite IDs (defaults to config targets)
            dry_run: If True, only show what would be changed
            include_disabled: If True, sync all variables (including disabled).
                            If False (default), only sync enabled variables.
            sync_changed_only: If True, compare source vs target and only sync
                             variables that have changed or are new.
                             If False (default), sync all filtered variables.
            config: Optional SyncConfig object (overrides individual parameters)

        Returns:
            Summary of all sync operations including statistics

        Examples:
            # Sync only enabled variables (default, safest)
            sync.sync_all()

            # Sync all variables including disabled
            sync.sync_all(include_disabled=True)

            # Sync only changed enabled variables (most efficient)
            sync.sync_all(sync_changed_only=True)

            # Use config object
            config = SyncConfig(dry_run=True, include_disabled=True)
            sync.sync_all(config=config)
        """
        # If config provided, use its values (overrides individual params)
        if config:
            dry_run = config.dry_run
            include_disabled = config.include_disabled
            sync_changed_only = config.sync_changed_only

        if target_rsids is None:
            target_rsids = self.rs_config.target_rsids

        logger.info("#" * 60)
        logger.info("STARTING FULL REPORT SUITE SYNC")
        logger.info(f"Source: {self.rs_config.production_rsid}")
        logger.info(f"Targets: {target_rsids}")
        logger.info(f"Options: dry_run={dry_run}, include_disabled={include_disabled}, "
                   f"sync_changed_only={sync_changed_only}")
        logger.info("#" * 60)

        results = {}

        # Sync each configuration type with the same parameters
        results["evars"] = self.sync_evars(
            target_rsids, dry_run, include_disabled, sync_changed_only
        )
        results["props"] = self.sync_props(
            target_rsids, dry_run, include_disabled, sync_changed_only
        )
        results["events"] = self.sync_events(
            target_rsids, dry_run, include_disabled, sync_changed_only
        )
        results["internal_url_filters"] = self.sync_internal_url_filters(target_rsids, dry_run)
        results["marketing_channels"] = self.sync_marketing_channels(target_rsids, dry_run)

        # Summarize results
        successful = sum(1 for r in results.values() if r.get("success"))
        failed = len(results) - successful

        summary = {
            "timestamp": datetime.now().isoformat(),
            "source_rsid": self.rs_config.production_rsid,
            "target_rsids": target_rsids,
            "config": {
                "dry_run": dry_run,
                "include_disabled": include_disabled,
                "sync_changed_only": sync_changed_only
            },
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
    print("=" * 60)
    
    # Step 1: Load OAuth credentials (from env vars or config file)
    oauth_config = OAuthConfig()
    
    if oauth_config.get_config_file() is None:
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
    sync = ReportSuiteSynchronizer()
    
    print("\nConnecting to Adobe Analytics...")
    if not sync.connect():
        print("❌ Connection failed. Check your credentials.")
        return
    
    print(f"✓ Connected to: {sync.company_name}")
    
    # Step 4: Create backup of dev report suite first
    print("\n" + "-" * 60)
    print("STEP 1: Creating backup of dev report suite...")
    print("-" * 60)
    backup = sync.backup_report_suite(rs_config.dev_rsid)
    
    # Step 5: Compare production vs dev
    print("\n" + "-" * 60)
    print("STEP 2: Comparing production vs dev report suites...")
    print("-" * 60)
    comparison = sync.compare_report_suites(
        rs_config.production_rsid,
        rs_config.dev_rsid
    )
    print(json.dumps(comparison, indent=2))
    
    # Step 6: Perform dry run with default settings (enabled-only)
    print("\n" + "-" * 60)
    print("STEP 3: Performing dry run sync (ENABLED variables only)...")
    print("-" * 60)
    dry_run_results = sync.sync_all(dry_run=True)

    # Step 6b: Show example of changed-only sync
    print("\n" + "-" * 60)
    print("STEP 3b: Preview of changed-only sync (more efficient)...")
    print("-" * 60)
    print("This would only sync variables that changed or are new:")
    print("  sync.sync_all(dry_run=True, sync_changed_only=True)")
    # Uncomment to try:
    # changed_only_results = sync.sync_all(dry_run=True, sync_changed_only=True)

    # Step 7: Prompt for actual sync (in production, you'd want proper confirmation)
    print("\n" + "-" * 60)
    print("STEP 4: Ready for actual sync")
    print("-" * 60)
    print("\nOptions for actual sync:")
    print("  # Default (enabled-only, safest):")
    print("  sync_results = sync.sync_all()")
    print("")
    print("  # Include disabled variables:")
    print("  sync_results = sync.sync_all(include_disabled=True)")
    print("")
    print("  # Only sync what changed (efficient):")
    print("  sync_results = sync.sync_all(sync_changed_only=True)")
    print("")
    print("  # Using SyncConfig:")
    print("  config = SyncConfig(include_disabled=False, sync_changed_only=True)")
    print("  sync_results = sync.sync_all(config=config)")

    # Uncomment to perform actual sync with your preferred options:
    # print("\nPerforming actual sync...")
    # sync_results = sync.sync_all()  # Default: enabled-only
    # print(json.dumps(sync_results, indent=2))

    print("\n" + "=" * 60)
    print("WORKFLOW COMPLETE")
    print("=" * 60)
    print("\nSummary of actions taken:")
    print("  1. ✓ Connected to Adobe Analytics")
    print("  2. ✓ Created backup of dev report suite")
    print("  3. ✓ Compared production vs dev configurations")
    print("  4. ✓ Performed dry run sync (enabled variables only)")
    print("  5. ⏸ Actual sync ready (uncomment with your preferred options)")
    print("\nNew in v1.1+:")
    print("  • Default syncs only ENABLED variables (safer)")
    print("  • Use include_disabled=True to sync all variables")
    print("  • Use sync_changed_only=True to sync only changes (efficient)")
    
    # Clean up temp config file if we created one
    temp_config = ".aa_config_from_env.json"
    if Path(temp_config).exists() and oauth_config.is_configured():
        Path(temp_config).unlink()


if __name__ == "__main__":
    main()