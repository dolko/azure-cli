import os
import time
from knack.prompting import prompt_choice_list, prompt_y_n, prompt
from azure_devops_build_manager.constants import (LINUX_CONSUMPTION, LINUX_DEDICATED, WINDOWS, PYTHON, NODE, NET, JAVA)
from .custom import list_function_app, list_devops_organizations, create_devops_project, list_devops_projects, create_yaml_file
from .custom import show_webapp, get_app_settings, list_devops_organizations_regions, create_devops_organization, list_devops_repositories, create_devops_repository, setup_devops_repository_locally
from .custom import list_service_principal_endpoints, create_service_principal_endpoint, create_extension, list_commits
from .custom import list_build_definitions, create_build_definition, create_build_object
from .custom import list_build_artifacts, create_release_definition, create_release_object

class AzureDevopsBuildInteractive(object):
    """Implement the basic user flow for a new user wanting to do an Azure DevOps build for Azure Functions

    Attributes:
        cmd : the cmd input from the command line
        logger : a knack logger to log the info/error messages
    """

    def __init__(self, cmd, logger):
        self.cmd = cmd
        self.logger = logger
        self.cmd_selector = CmdSelectors(cmd, logger)


    def interactive_azure_devops_build(self, functionapp_name=None, organization_name=None, project_name=None):
        """Main interactive flow which is the only function that should be used outside of this
        class (the rest are helpers)
        """
        storage_name, functionapp, functionapp_name,\
            language, functionapp_type = self._get_functionapp(self.cmd, functionapp_name)
        organization, organization_name, created_organization = self._get_organization(self.cmd, organization_name)
        project = self._get_project(self.cmd, organization_name, created_organization, project_name)

        

        # TODO repository name needs to change if the repository already exists + this will effect build definition name
        project_name = project.name
        repository_name = project_name
        service_endpoint_name = organization_name + project_name
        build_definition_name = project_name
        pool_name = "Default"



        if os.path.exists('azure-pipelines.yml'):
            response = prompt_y_n("There is already an azure pipelines yaml file. Do you want to delete it and create a new one? ")
        if (not os.path.exists('azure-pipelines.yml')) or response:
            create_yaml_file(self.cmd, language, functionapp_type,
                             functionapp_name, service_endpoint_name, storage_name)

        self._get_repository(organization_name, project_name, repository_name)
        self._get_service_endpoint(organization_name, project_name, service_endpoint_name)

        self.logger.info("Installing the required extensions for the build and release")
        create_extension(self.cmd, organization_name, 'AzureAppServiceSetAppSettings', 'hboelman')
        create_extension(self.cmd, organization_name, 'PascalNaber-Xpirit-CreateSasToken', 'pascalnaber')

        self.logger.info("Initiating the build")
        build = self._get_build(organization_name, project_name, repository_name, build_definition_name, pool_name)

        self.logger.info("Initiating the release")
        self._get_release(organization_name, project_name, build, build_definition_name, service_endpoint_name, functionapp, functionapp_type, functionapp_name, storage_name)

        self.logger.info("Finished the release. Please follow it here: ")

    def _select_functionapp(self, cmd):
        self.logger.info("Retrieving functionapp names ...")
        functionapps = list_function_app(cmd)
        functionapp_names = [functionapp.name for functionapp in functionapps]
        functionapp_names = sorted(functionapp_names)
        choice_index = prompt_choice_list('Please choose the functionapp: ', functionapp_names)
        functionapp = [functionapp for functionapp in functionapps
                       if functionapp.name == functionapp_names[choice_index]][0]
        self.logger.info("Selected functionapp %s", functionapp.name)
        return functionapp

    def _find_language_and_storage_name(self, app_settings):
        for app_setting in app_settings:
            if app_setting['name'] == "FUNCTIONS_WORKER_RUNTIME":
                language_str = app_setting['value']
                if language_str == "python":
                    self.logger.info("detected that language used by functionapp is python")
                    language = PYTHON
                elif language_str == "node":
                    self.logger.info("detected that language used by functionapp is node")
                    language = NODE
                elif language_str == "net":
                    self.logger.info("detected that language used by functionapp is .net")
                    language = NET
                elif language_str == "java":
                    self.logger.info("detected that language used by functionapp is java")
                    language = JAVA
                else:
                    self.logger.warning("valid language not found")
                    language = ""
            if app_setting['name'] == "AzureWebJobsStorage":
                storage_name = app_setting['value'].split(';')[1].split('=')[1]
                self.logger.info("detected that storage used by the functionapp is %s", storage_name)
        return language, storage_name

    def _find_type(self, kinds):
        if 'linux' in kinds:
            if 'container' in kinds:
                functionapp_type = LINUX_DEDICATED
            else:
                functionapp_type = LINUX_CONSUMPTION
        else:
            functionapp_type = WINDOWS
        return functionapp_type

    def _get_functionapp(self, cmd, functionapp_name):
        """Helper to retrieve information about a functionapp"""
        if functionapp_name is None:
            functionapp = self._select_functionapp(cmd)
        else:
            functionapp = self.cmd_selector.cmd_functionapp(functionapp_name)
        functionapp_name = functionapp.name
        functionapp_details = show_webapp(cmd, functionapp.resource_group, functionapp.name)
        kinds = functionapp_details.kind.split(',')
        functionapp_type = self._find_type(kinds)
        app_settings = get_app_settings(cmd, functionapp.resource_group, functionapp.name)
        language, storage_name = self._find_language_and_storage_name(app_settings)
        return storage_name, functionapp, functionapp.name, language, functionapp_type

    def _select_organization(self, cmd):
        organizations = list_devops_organizations(cmd)
        organization_names = [organization.accountName for organization in organizations.value]
        organization_names = sorted(organization_names)
        choice_index = prompt_choice_list('Please choose the organization: ', organization_names)
        organization_matches = [organization for organization in organizations.value if organization.accountName == organization_names[choice_index]]
        if len(organization_matches) < 1:
            self.logger.error("There are not any existing organizations")
            exit(1)
        organization = organization_matches[0]
        organization_name = organization.accountName
        return organization, organization_name

    def _create_organization(self, cmd):
        self.logger.info("Creating a new organization")
        regions = list_devops_organizations_regions(cmd)
        region_names = [region.display_name for region in regions.value]
        region_names = sorted(region_names)
        choice_index = prompt_choice_list('Please select a region for the new organization: ', region_names)
        region = [region for region in regions.value if region.display_name == region_names[choice_index]][0]

        while(True):
            organization_name = prompt("Please enter the name of the new organization: ")
            obj = create_devops_organization(cmd, organization_name, region.regionCode)
            if hasattr(obj, 'valid'):
                if obj.valid is False:
                    self.logger.warning(obj.message)
                    self.logger.warning("Note: any name must be globally unique")
                else:
                    break
            else:
                break
        self.logger.info("Finished creating the new organization: %s", obj.name)
        return obj, organization_name

    def _get_organization(self, cmd, organization_name):
        created_organization = False
        if organization_name is None:
            response = prompt_y_n('Would you like to use an existing organization? ')
            if response:
                organization, organization_name = self._select_organization(cmd)
            else:
                organization, organization_name = self._create_organization(cmd)
                created_organization = True
        else:
            organization = self.cmd_selector.cmd_organization(organization_name)
        
        return organization, organization_name, created_organization

    def _select_project(self, cmd, organization_name):
        projects = list_devops_projects(cmd, organization_name)
        if projects.count > 0:
            project_names = [project.name for project in projects.value]
            project_names = sorted(project_names)
            choice_index = prompt_choice_list('Please select a region for the new organization: ', project_names)
            project = [project for project in projects.value if project.name == project_names[choice_index]][0]
        else:
            self.logger.warning("There are no exisiting projects in this organization")
            self.logger.warning("You need to make a new project")
            project = None
        return project

    def _create_project(self, cmd, organization_name):
        project_name = prompt("Please enter the name of the new project: ")
        project = create_devops_project(cmd, organization_name, project_name)
        return project

    def _get_project(self, cmd, organization_name, created_organization, project_name):
        if project_name is None:
            if created_organization:
                # We can't use an existing project if we just made the organization 
                # as there won't be any projects inside
                use_existing_project = True
            else:
                use_existing_project = prompt_y_n('Would you like to use an existing project? ')
            if use_existing_project:
                project = self._select_project(cmd, organization_name)
            if (not use_existing_project) or (project is None):
                project = self._create_project(cmd, organization_name)
        else:
            project = self.cmd_selector.cmd_project(organization_name, project_name)
        return project

    def _get_repository_new(self, organization_name, project_name, repository_name):
        # check if we need to make a repository
        repositories = list_devops_repositories(self.cmd, organization_name, project_name)
        repository_match = \
            [repository for repository in repositories if repository.name == repository_name]

        if len(repository_match) != 1:
            repository = create_devops_repository(self.cmd, organization_name, project_name, repository_name)
        else:
            repository = repository_match[0]

        #detect if they have a git file locally
        resonse = False
        if os.path.exists(".git"):
            self.logger.warning("There is a local git file.")
            response = prompt_y_n('Would you like to use the git repository that you are referencing locally? ')
            
            if response:
                # get the user to select from types of supported repositories

                # TODO for github : https://docs.microsoft.com/en-us/rest/api/azure/devops/build/source%20providers/list?view=azure-devops-rest-5.0
                
            else:

        else:
            print("yo")
        #yes
        #want to use it?
        #yes -> options on


        setup = setup_devops_repository_locally(self.cmd, organization_name, project_name, repository_name)

        if not setup.succeeded:
            response = prompt_y_n('To continue we need to remove the current git file locally. Is this okay? ')
            # need to remove the current git repository
            if response:
                # TODO consider the linux command for removing the file
                os.system("rmdir /s /q .git")
                setup_devops_repository_locally(self.cmd, organization_name, project_name, repository_name)
            else:
                exit(1)

        return repository


        commits = list_commits(self.cmd, organization_name, project_name, repository_name)
        if not commits:
            self.logger.info("the default repository is empty")
        else:
            self.logger.warning("the repository already contains a commit - you need to start a new repository")
            response = prompt_y_n('ya dee ')


    def _get_repository(self, organization_name, project_name, repository_name):
        # check if we need to make a repository
        repositories = list_devops_repositories(self.cmd, organization_name, project_name)
        repository_match = \
            [repository for repository in repositories if repository.name == repository_name]

        if len(repository_match) != 1:
            repository = create_devops_repository(self.cmd, organization_name, project_name, repository_name)
        else:
            repository = repository_match[0]

        setup = setup_devops_repository_locally(self.cmd, organization_name, project_name, repository_name)

        if not setup.succeeded:
            # TODO need to consider being able to link up their existing repository here
            response = prompt_y_n('To continue we need to remove the current git file locally. Is this okay? ')
            # need to remove the current git repository
            if response:
                # TODO consider the linux command for removing the file
                os.system("rmdir /s /q .git")
                # rerun the setup
                setup_devops_repository_locally(self.cmd, organization_name, project_name, repository_name)
            else:
                exit(1)

        return repository

    def _get_service_endpoint(self, organization_name, project_name, service_endpoint_name):
        service_endpoints = list_service_principal_endpoints(self.cmd, organization_name, project_name)
        service_endpoint_match = \
            [service_endpoint for service_endpoint in service_endpoints if service_endpoint.name == service_endpoint_name]

        if len(service_endpoint_match) != 1:
            service_endpoint = create_service_principal_endpoint(self.cmd, organization_name, project_name, service_endpoint_name)
        else:
            service_endpoint = service_endpoint_match[0]

        return service_endpoint

    def _get_build(self, organization_name, project_name, repository_name, build_definition_name, pool_name):
        # need to check if the build definition already exists
        build_definitions = list_build_definitions(self.cmd, organization_name, project_name)
        build_definition_match = \
            [build_definition for build_definition in build_definitions if build_definition.name == build_definition_name]

        if len(build_definition_match) != 1:
            create_build_definition(self.cmd, organization_name, project_name, repository_name, build_definition_name, pool_name)
    
        self.logger.info("creating build definition")
        build = create_build_object(self.cmd, organization_name, project_name, build_definition_name, pool_name)
        return build

    def _get_release(self, organization_name, project_name, build, build_definition_name, service_endpoint_name, functionapp, functionapp_type,
                     functionapp_name, storage_name):
        # wait for artifacts / build to complete
        artifacts = []
        while artifacts == []:
            time.sleep(1)
            self.logger.info("waiting for artifacts ...")
            artifacts = list_build_artifacts(self.cmd, organization_name, project_name, build.id)

        # need to create a release pipelines that uses the artifacts from the build
        artifact_name = "drop"
        release_definition_name = build_definition_name + " release"
        resource_name = functionapp.resource_group
        # All of the releases use a windows vm to release
        pool_name = "Hosted VS2017"
        create_release_definition(self.cmd, organization_name, project_name, build_definition_name, artifact_name, pool_name,
                                service_endpoint_name, release_definition_name, functionapp_type, functionapp_name, storage_name, resource_name)
        release = create_release_object(self.cmd, organization_name, project_name, release_definition_name)
        return release


class CmdSelectors(object):

    def __init__(self, cmd, logger):
        self.cmd = cmd
        self.logger = logger

    def cmd_functionapp(self, functionapp_name):
        functionapps = list_function_app(self.cmd)
        functionapp_match = [functionapp for functionapp in functionapps
                             if functionapp.name == functionapp_name]
        if len(functionapp_match) != 1:
            self.logger.error("""Error finding functionapp. Please check that the 
                              functionapp exists using 'az functionapp list'""")
            exit(1)
        else:
            functionapp = functionapp_match[0]
        return functionapp

    def cmd_organization(self, organization_name):
        organizations = list_devops_organizations(self.cmd)
        organization_match = [organization for organization in organizations.value
                              if organization.accountName == organization_name]
        if len(organization_match) != 1:
            self.logger.error("""Error finding organization. Please check that the 
                              organization exists using 'functionapp devops-build organization list'""")
            exit(1)
        else:
            organization = organization_match[0]
        return organization

    def cmd_project(self, organization_name, project_name):
        #validate that the project exists
        projects = list_devops_projects(self.cmd, organization_name)
        project_match = \
            [project for project in projects.value if project.name == project_name]

        if len(project_match) != 1:
            self.logger.error("Error finding project. Please check that the project exists using 'functionapp devops-build project list'")
            exit(1)
        else:
            project = project_match[0]
        return project