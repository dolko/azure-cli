# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from __future__ import print_function
from azure.cli.core._profile import Profile

from azure_devops_build_manager.organization.organization_manager import OrganizationManager
from azure_devops_build_manager.user.user_manager import UserManager
from azure_devops_build_manager.project.project_manager import ProjectManager
from azure_devops_build_manager.yaml.yaml_manager import YamlManager
from azure_devops_build_manager.respository.repository_manager import RepositoryManager
from azure_devops_build_manager.pool.pool_manager import PoolManager
from azure_devops_build_manager.service_endpoint.service_endpoint_manager import ServiceEndpointManager
from azure_devops_build_manager.extension.extension_manager import ExtensionManager
from azure_devops_build_manager.builder.builder_manager import BuilderManager
from azure_devops_build_manager.artifact.artifact_manager import ArtifactManager
from azure_devops_build_manager.release.release_manager import ReleaseManager
# pylint: disable=line-too-long

class AzureDevopsBuildProvider(object):
    def __init__(self, cli_ctx):
        profile = Profile(cli_ctx=cli_ctx)
        self._creds, _, _ = profile.get_login_credentials(subscription_id=None)

    def list_organizations(self):
        organization_manager = OrganizationManager(creds=self._creds)
        user_manager = UserManager(creds=self._creds)
        userid = user_manager.get_user_id()
        organizations = organization_manager.list_organizations(userid.id)
        return organizations

    def list_regions(self):
        organization_manager = OrganizationManager(creds=self._creds)
        regions = organization_manager.list_regions()
        return regions

    def create_organization(self, organization_name, regionCode):
        # validate the organization name
        organization_manager = OrganizationManager(creds=self._creds)
        validation = organization_manager.validate_organization_name(organization_name)
        if not validation.valid:
            return validation

        #validate region code:
        valid_region = False
        for region in self.list_regions().value:
            if region.regionCode == regionCode:
                valid_region = True
        if not valid_region:
            error_message = {}
            error_message['message'] = "not a valid region code - run 'az functionapp devops-build organization' regions to find a valid regionCode"
            error_message['valid'] = False
            return error_message

        new_organization = organization_manager.create_organization(regionCode, organization_name)
        new_organization.valid = True
        return new_organization

    def list_projects(self, organization_name):
        project_manager = ProjectManager(organization_name=organization_name, creds=self._creds)
        projects = project_manager.list_projects()
        return projects

    def create_project(self, organization_name, project_name):
        project_manager = ProjectManager(organization_name=organization_name, creds=self._creds)
        project = project_manager.create_project(project_name)
        return project

    def create_yaml(self, language, appType, functionapp_name, subscription_name, storage_name):
        yaml_manager = YamlManager(language, appType)
        # TODO when devops switch to all in one yaml file you will need to add an include release paramater and set it to true
        yaml_manager.create_yaml(functionapp_name, subscription_name, storage_name, include_release=False)

    def create_repository(self, organization_name, project_name, repository_name):
        repository_manager = RepositoryManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return repository_manager.create_repository(repository_name)

    def list_repositories(self, organization_name, project_name):
        repository_manager = RepositoryManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return repository_manager.list_repositories()

    def list_commits(self, organization_name, project_name, repository_name):
        repository_manager = RepositoryManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return repository_manager.list_commits(repository_name)

    def setup_repository(self, organization_name, project_name, repository_name):
        repository_manager = RepositoryManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return repository_manager.setup_repository(repository_name)

    def list_pools(self, organization_name, project_name):
        pool_manager = PoolManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return pool_manager.list_pools()

    def create_service_endpoint(self, organization_name, project_name, name):
        service_endpoint_manager = ServiceEndpointManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return service_endpoint_manager.create_service_endpoint(name)

    def list_service_endpoints(self, organization_name, project_name):
        service_endpoint_manager = ServiceEndpointManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return service_endpoint_manager.list_service_endpoints()

    def create_extension(self, organization_name, extension_name, publisher_name):
        extension_manager = ExtensionManager(organization_name=organization_name, creds=self._creds)
        return extension_manager.create_extension(extension_name, publisher_name)

    def list_extensions(self, organization_name):
        extension_manager = ExtensionManager(organization_name=organization_name, creds=self._creds)
        return extension_manager.list_extensions()

    def create_build_definition(self, organization_name, project_name, repository_name, build_definition_name, pool_name):
        builder_manager = BuilderManager(organization_name=organization_name, project_name=project_name, repository_name=repository_name, \
                                             creds=self._creds)
        return builder_manager.create_definition(build_definition_name=build_definition_name, pool_name=pool_name)

    def list_build_definition(self, organization_name, project_name):
        builder_manager = BuilderManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return builder_manager.list_definitions()

    def create_build_object(self, organization_name, project_name, build_definition_name, pool_name):
        builder_manager = BuilderManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return builder_manager.create_build(build_definition_name, pool_name)

    def list_build_object(self, organization_name, project_name):
        builder_manager = BuilderManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return builder_manager.list_builds()

    def list_artifacts(self, organization_name, project_name, build_id):
        artifact_manager = ArtifactManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return artifact_manager.list_artifacts(build_id)

    def create_release_definition(self, organization_name, project_name, build_name, artifact_name, pool_name, service_endpoint_name,
                                  release_definition_name, app_type, functionapp_name, storage_name, resource_name):
        release_manager = ReleaseManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return release_manager.create_release_definition(build_name, artifact_name, pool_name, service_endpoint_name, release_definition_name,
                                                         app_type, functionapp_name, storage_name, resource_name)

    def list_release_definitions(self, organization_name, project_name):
        release_manager = ReleaseManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return release_manager.list_release_definitions()

    def create_release(self, organization_name, project_name, release_definition_name):
        release_manager = ReleaseManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return release_manager.create_release(release_definition_name)

    def list_releases(self, organization_name, project_name):
        release_manager = ReleaseManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return release_manager.list_releases()

    def create_github_repository_auth(self, organization_name, project_name):
        repository_manager = RepositoryManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return repository_manager.create_github_connection()

    def list_github_repositories(self, organization_name, project_name):
        repository_manager = RepositoryManager(organization_name=organization_name, project_name=project_name, creds=self._creds)
        return repository_manager.list_github_repositories()