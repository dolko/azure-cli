# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from __future__ import print_function
from sys import stderr
from azure.cli.core._profile import Profile
from msrest.service_client import ServiceClient
from msrest import Configuration

from azure_devops_build_manager.organization.organization_manager import OrganizationManager
from azure_devops_build_manager.user.user_manager import UserManager


class AzureDevopsBuildProvider(object):
    def __init__(self, cli_ctx):
        profile = Profile(cli_ctx=cli_ctx)
        creds, _, _ = profile.get_login_credentials(subscription_id=None)
        self.organization_manager = OrganizationManager(creds=creds)
        self.user_manager = UserManager(creds=creds)
        self._progress_last_message = ''

    def list_organizations(self):
        userid = self.user_manager.get_user_id()
        organizations = self.organization_manager.get_organizations(userid.id)
        return organizations

    def list_regions(self):
        regions = self.organization_manager.get_regions()
        return regions

    def create_organization(self, name, regionCode):
        # validate the organization name
        validation = self.organization_manager.validate_organization_name(name)
        if not validation.valid:
            return validation

        #validate region code:
        valid_region = False
        for region in self.list_regions().value:
            if region.regionCode == regionCode:
                valid_region = True
        if not valid_region:
            error_message = {}
            error_message['message'] = "not a valid region code - run az functionapp devops-build organization regions to find a valid regionCode"
            error_message['valid'] = False
            return error_message

        new_organization = self.organization_manager.create_organization(regionCode, name)
        return new_organization
