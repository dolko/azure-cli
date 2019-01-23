import os
from subprocess import check_output
import time
import re
import json
from knack.prompting import prompt_choice_list, prompt_y_n, prompt
from azure_functions_devops_build.constants import (LINUX_CONSUMPTION, LINUX_DEDICATED, WINDOWS,
                                                    PYTHON, NODE, DOTNET, JAVA)
from .azure_devops_build_provider import AzureDevopsBuildProvider
from .custom import list_function_app, show_webapp, get_app_settings

class AzureDevopsBuildInteractive(object):
    """Implement the basic user flow for a new user wanting to do an Azure DevOps build for Azure Functions

    Attributes:
        cmd : the cmd input from the command line
        logger : a knack logger to log the info/error messages
    """

    def __init__(self, cmd, logger, functionapp_name, organization_name, project_name):
        self.adbp = AzureDevopsBuildProvider(cmd.cli_ctx)
        self.cmd = cmd
        self.logger = logger
        self.cmd_selector = CmdSelectors(cmd, logger)
        self.functionapp_name = functionapp_name
        self.storage_name = None
        self.resource_group_name = None
        self.functionapp_language = None
        self.functionapp_type = None
        self.organization_name = organization_name
        self.project_name = project_name
        self.repository_name = None
        self.service_endpoint_name = None
        self.build_definition_name = None
        self.release_definition_name = None
        self.build_pool_name = "Default"
        self.release_pool_name = "Hosted VS2017"
        self.artifact_name = "drop"

        self.settings = []
        self.build = None
        self.release = None
        # These are used to tell if we made new objects
        self.created_organization = False
        self.created_project = False
        self.github_used = False


    def interactive_azure_devops_build(self):
        """Main interactive flow which is the only function that should be used outside of this
        class (the rest are helpers)
        """
        self.process_functionapp()
        self.process_organization()
        self.process_project()

        # Set up the default names for the rest of the things we need to create
        self.repository_name = self.project_name
        self.service_endpoint_name = self.organization_name + self.project_name
        self.build_definition_name = self.project_name + " INITIAL AZ CLI BUILD"
        self.release_definition_name = self.project_name + " INITIAL AZ CLI RELEASE"

        self.process_yaml()
        self.process_repository()

        self.process_service_endpoint()
        self.process_extensions()

        self.process_build()
        self.process_release()

    def process_functionapp(self):
        """Helper to retrieve information about a functionapp"""
        if self.functionapp_name is None:
            functionapp = self._select_functionapp()
            # We now know the functionapp name so can set it
            self.functionapp_name = functionapp.name
        else:
            functionapp = self.cmd_selector.cmd_functionapp(self.functionapp_name)

        kinds = show_webapp(self.cmd, functionapp.resource_group, functionapp.name).kind.split(',')
        app_settings = get_app_settings(self.cmd, functionapp.resource_group, functionapp.name)

        self.resource_group_name = functionapp.resource_group
        self.functionapp_type = self._find_type(kinds)
        self.functionapp_language, self.storage_name = self._find_language_and_storage_name(app_settings)


    def process_organization(self):
        """Helper to retrieve information about an organization / create a new one"""
        if self.organization_name is None:
            response = prompt_y_n('Would you like to use an existing organization? ')
            if response:
                self._select_organization()
            else:
                self._create_organization()
                self.created_organization = True
        else:
            self.cmd_selector.cmd_organization(self.organization_name)

    def process_project(self):
        """Helper to retrieve information about a project / create a new one"""
        # There is a new organization so a new project will be needed
        if (self.project_name is None) and (self.created_organization):
            self._create_project()
        elif self.project_name is None:
            use_existing_project = prompt_y_n('Would you like to use an existing project? ')
            if use_existing_project:
                self._select_project()
            else:
                self._create_project()
        else:
            self.cmd_selector.cmd_project(self.organization_name, self.project_name)

    def process_yaml(self):
        # Try and get what the app settings are
        with open('local.settings.json') as f:
            data = json.load(f)

        default = ['FUNCTIONS_WORKER_RUNTIME', 'AzureWebJobsStorage']
        settings = []
        for key, value in data['Values'].items():
            if key not in default:
                settings.append((key, value))

        if settings:
            use_local_settings = prompt_y_n('Would you like to use your local settings on your host settings?')
            if not use_local_settings:
                settings = []

        self.settings = settings

        if os.path.exists('azure-pipelines.yml'):
            response = prompt_y_n("There is already an azure pipelines yaml file. Do you want to delete it and create a new one? ")
        if (not os.path.exists('azure-pipelines.yml')) or response:
            self.adbp.create_yaml(self.functionapp_language, self.functionapp_type)

    def process_repository(self):
        if os.path.exists(".git"):
            self.process_git_exists()
        else:
            self.process_git_doesnt_exist()

    def process_extensions(self):
        self.logger.info("Installing the required extensions for the build and release")
        self.adbp.create_extension(self.organization_name, 'AzureAppServiceSetAppSettings', 'hboelman')
        self.adbp.create_extension(self.organization_name, 'PascalNaber-Xpirit-CreateSasToken', 'pascalnaber')

    def process_service_endpoint(self):
        service_endpoints =  self.adbp.list_service_endpoints(self.organization_name, self.project_name)
        service_endpoint_match = \
            [service_endpoint for service_endpoint in service_endpoints
             if service_endpoint.name == self.service_endpoint_name]

        if len(service_endpoint_match) != 1:
            service_endpoint = self.adbp.create_service_endpoint(self.organization_name, self.project_name,
                                                                 self.service_endpoint_name)
        else:
            service_endpoint = service_endpoint_match[0]
        return service_endpoint

    def process_build(self):
        # need to check if the build definition already exists
        build_definitions = self.adbp.list_build_definitions(self.organization_name, self.project_name)
        build_definition_match = \
            [build_definition for build_definition in build_definitions
             if build_definition.name == self.build_definition_name]

        if len(build_definition_match) != 1:
            self.adbp.create_build_definition(self.organization_name, self.project_name,
                                              self.repository_name, self.build_definition_name,
                                              self.build_pool_name)

        build = self.adbp.create_build_object(self.organization_name, self.project_name,
                                              self.build_definition_name, self.build_pool_name)

        url = "https://dev.azure.com/" + self.organization_name + "/" + self.project_name + "/_build/results?buildId=" + str(build.id)
        self.logger.info("To follow the build process go to %s", url)
        self.build = build

    def process_release(self):
        # wait for artifacts / build to complete
        artifacts = []
        counter = 0
        while artifacts == []:
            time.sleep(1.5)
            self.logger.info("waiting for artifacts ... %s", counter)
            build = self._get_build_by_id(self.organization_name, self.project_name, self.build.id)
            if build.status == 'completed':
                break
            artifacts = self.adbp.list_artifacts(self.organization_name, self.project_name, self.build.id)
            counter += 1

        if build.result == 'failed':
            url = "https://dev.azure.com/" + self.organization_name + "/" + self.project_name + "/_build/results?buildId=" + str(build.id)
            self.logger.critical("Your build has failed")
            self.logger.critical("To view details on why your build has failed please go to %s", url)
            exit(1)

        self.adbp.create_release_definition(self.organization_name, self.project_name,
                                            self.build_definition_name, self.artifact_name, self.release_pool_name,
                                            self.service_endpoint_name, self.release_definition_name, self.functionapp_type,
                                            self.functionapp_name, self.storage_name, self.resource_group_name, self.settings)
        release = self.adbp.create_release(self.organization_name, self.project_name,
                                           self.release_definition_name)

        url = "https://dev.azure.com/" + self.organization_name + "/" + self.project_name + "/_releaseProgress?_a=release-environment-logs&releaseId=" + str(release.id)
        self.logger.info("To follow the release process go to %s", url)
        self.release = release

    def find_type_repository(self):
        lines = (check_output('git remote show origin'.split())).decode('utf-8').split('\n')
        for line in lines:
            if re.search('github', line):
                return 'github'
            elif re.search('visualstudio', line):
                return 'azure repos'
        return 'other'

    def setup_devops_repository_with_existing(self):
        command_options = ['Delete git folder locally (linux)', 'Delete git file locally (windows)', 'Add a remote']
        choice_index = prompt_choice_list('Please choose the action you would like to take: ', command_options)
        command = command_options[choice_index]

        if command == 'Delete git folder locally (linux)':
            os.system("rm -rf .git")
            self.process_git_doesnt_exist()
        elif command == 'Delete git file locally (windows)':
            os.system("rmdir /s /q .git")
            self.process_git_doesnt_exist()
        else:
            setup = self.adbp.setup_remote(self.organization_name, self.project_name,
                                           self.repository_name, 'devopsbuild')
            if not setup.succeeded:
                self.logger.critical('It looks like you already have a remote called devopsbuild. This indicates that you already likely have a pipeline setup.')
                self.logger.critical('Please either delete the local git file or use that already setup pipeline')
                exit(1)

    def process_git_exists(self):
        self.logger.warning("There is a local git file.")
        response = prompt_y_n('Would you like to use the git repository that you are referencing locally? ')

        if response:
            repository_type = self.find_type_repository()
            self.logger.info("We have detected that you have a %s type of repository", repository_type)
            if repository_type == 'github':
                # They need to login and connect up their github account
                github_connection = self._create_github_connection()
                print("Please click the following link to finish your authentication: %s", github_connection.url)
                finished = prompt_y_n('Type y to continue one you have finished logging into your github account. Type n if you had an issue')
                if not finished:
                    url = "https://dev.azure.com/" + self.organization_name + "/" + self.project_name + "/_build"
                    print("You can try setting up the authentication manually. Go to %s .", url)
                    print("Select new pipeline. When you are prompted with where is your code click 'Github'. Click authorize.")
                    finished_2 = prompt_y_n('Type y to continue one you have finished authorizing. Type n if you had an issue')
                    if not finished_2:
                        self.logger.error("We were unsuccessful in setting up your github connection. Please follow another option below NOT involving your github account.")
                        self.setup_devops_repository_with_existing()
                if finished or finished_2:
                    # TODO validate that the connection worked
                    # TODO validate if we need the name of the github account??
                    self.github_used = True
            elif repository_type == 'azure repos':
                # Figure out what the repository information is for their current azure repos account
                lines = (check_output('git remote show origin'.split())).decode('utf-8').split('\n')
                for line in lines:
                    if re.search('Push',line):
                        m = re.search('http.*', line)
                        url = m.group(0)
                        segs = url.split('/')
                        organization_name = segs[2].split('.')[0]
                        project_name = segs[3]
                        repository_name = segs[5]
                if (organization_name == self.organization_name) and (project_name == self.project_name):
                    print("It looks like your local repository is the same as the one you are trying to make a build for")
                    self.repository_name = repository_name
                else:
                    print("It looks like your local repository IS NOT the same as the one you are trying to make a build for")
                    switch = prompt_y_n('Would you like to use the repository that you are currently referencing locally to do the build?')
                    if switch:
                        # We don't need to push to it as it is all currently there
                        self.organization_name = organization_name
                        self.project_name = project_name
                        self.repository_name = repository_name
                    else:
                        self.setup_devops_repository_with_existing()
            else:
                self.logger.error("We don't support any other repositories except for github and azure repos. We cannot setup a build with these repositories.") # pylint: disable=line-too-long
                self.setup_devops_repository_with_existing()
        else:
            self.setup_devops_repository_with_existing()
         

    def process_git_doesnt_exist(self):
        # check if we need to make a repository
        repositories = self.adbp.list_repositories(self.organization_name, self.project_name)
        repository_match = \
            [repository for repository in repositories if repository.name == self.repository_name]

        if not repository_match:
            # Since we don't have a match for that repository we should just make it
            repository = self.adbp.create_repository(self.organization_name, self.project_name, self.repository_name)
        else:
            repository = repository_match[0]
            commits = self.adbp.list_commits(self.organization_name, self.project_name, self.repository_name)
            if commits:
                self.logger.warning("The default repository associated with your project already contains a commit. There needs to be a clean repository.") # pylint: disable=line-too-long
                succeeded = False
                while not succeeded:
                    repository_name = prompt('We will create that repository. What would you like to call the new repository?')
                    # Validate that the name does not already exist
                    repositories = self.adbp.list_repositories(self.organization_name, self.project_name)
                    repository_match = \
                        [repo for repo in repositories if repo.name == repository_name]
                    if repository_match:
                        self.logger.error("A repository with that name already exists in this project.")
                    else:
                        succeeded = True
                repository = self.adbp.create_repository(self.organization_name, self.project_name, repository_name)
                self.repository_name = repository_name
                self.build_definition_name += repository_name
                self.release_definition_name += repository_name
        # Since they do not have a git file locally we can setup the git locally as is
        self.adbp.setup_repository(self.organization_name, self.project_name, self.repository_name)

    def _select_functionapp(self):
        self.logger.info("Retrieving functionapp names.")
        functionapps = list_function_app(self.cmd)
        functionapp_names = sorted([functionapp.name for functionapp in functionapps])
        choice_index = prompt_choice_list('Please choose the functionapp: ', functionapp_names)
        functionapp = [functionapp for functionapp in functionapps
                       if functionapp.name == functionapp_names[choice_index]][0]
        self.logger.info("Selected functionapp %s", functionapp.name)
        return functionapp

    def _find_local_language(self):
        # We want to check that locally the language that they are using matches the type of application they
        # are deploying to
        with open('local.settings.json') as f:
            settings = json.load(f)
        try:
            local_language = settings['Values']['FUNCTIONS_WORKER_RUNTIME']
        except KeyError:
            self.logger.critical('The app \'FUNCTIONS_WORKER_RUNTIME\' setting is not set in the local.settings.json file') # pylint: disable=line-too-long
            exit(1)
        if local_language == '':
            self.logger.critical('The app \'FUNCTIONS_WORKER_RUNTIME\' setting is not set in the local.settings.json file') # pylint: disable=line-too-long
            exit(1)
        return local_language

    def _find_language_and_storage_name(self, app_settings):
        local_language = self._find_local_language()
        for app_setting in app_settings:
            if app_setting['name'] == "FUNCTIONS_WORKER_RUNTIME":
                language_str = app_setting['value']
                if language_str != local_language:
                    # We should not deploy if the local runtime language is not the same as that of their functionapp
                    self.logger.critical("ERROR: The local language you are using (%s) does not match the language of your functionapp (%s)", local_language, language_str) # pylint: disable=line-too-long
                    self.logger.critical("Please look at the FUNCTIONS_WORKER_RUNTIME both in your local.settings.json and in your application settings on your azure functionapp.") # pylint: disable=line-too-long
                    exit(1)
                if language_str == "python":
                    self.logger.info("detected that language used by functionapp is python")
                    language = PYTHON
                elif language_str == "node":
                    self.logger.info("detected that language used by functionapp is node")
                    language = NODE
                elif language_str == "dotnet":
                    self.logger.info("detected that language used by functionapp is .net")
                    language = DOTNET
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

    def _select_organization(self):
        organizations = self.adbp.list_organizations()
        organization_names = sorted([organization.accountName for organization in organizations.value])
        if len(organization_names) < 1:
            self.logger.error("There are not any existing organizations, you need to create a new organization.")
            self._create_organization()
            self.created_organization = True
        else:
            choice_index = prompt_choice_list('Please choose the organization: ', organization_names)
            organization_match = [organization for organization in organizations.value
                                  if organization.accountName == organization_names[choice_index]
                                 ][0]
            self.organization_name = organization_match.accountName

    def _get_organization_by_name(self, organization_name):
        organizations = self.adbp.list_organizations()
        return [organization for organization in organizations.value if organization.accountName == organization_name][0]

    def _create_organization(self):
        self.logger.info("Starting process to create a new Azure DevOps organization")
        regions = self.adbp.list_regions()
        region_names = sorted([region.display_name for region in regions.value])
        self.logger.info("The region for an Azure DevOps organization is where the organization will be located. Try locate it near your other resources and your location")
        choice_index = prompt_choice_list('Please select a region for the new organization: ', region_names)
        region = [region for region in regions.value if region.display_name == region_names[choice_index]][0]

        while True:
            organization_name = prompt("Please enter the name of the new organization: ")
            new_organization = self.adbp.create_organization(organization_name, region.regionCode)
            if new_organization.valid is False:
                self.logger.warning(new_organization.message)
                self.logger.warning("Note: any name must be globally unique")
            else:
                break

        url = "https://dev.azure.com/" + new_organization.name + "/"
        self.logger.info("Finished creating the new organization. Click the link to see your new organization: %s", url)
        self.organization_name = new_organization.name

    def _select_project(self):
        projects = self.adbp.list_projects(self.organization_name)
        if projects.count > 0:
            project_names = sorted([project.name for project in projects.value])
            choice_index = prompt_choice_list('Please select a region for the new organization: ', project_names)
            project = [project for project in projects.value if project.name == project_names[choice_index]][0]
            self.project_name = project.name
        else:
            self.logger.warning("There are no exisiting projects in this organization. You need to create a new project.")
            self._create_project()

    def _create_project(self):
        project_name = prompt("Please enter the name of the new project: ")
        project = self.adbp.create_project(self.organization_name, project_name)
        # Keep retrying to create a new project if it fails
        while not project.valid:
            self.logger.error(project.message)
            project_name = prompt("Please enter the name of the new project: ")
            project = self.adbp.create_project(self.organization_name, project_name)

        url = "https://dev.azure.com/" + self.organization_name + "/" + project.name +"/"
        self.logger.info("Finished creating the new project. Click the link to see your new project: %s", url)
        self.project_name = project.name
        self.created_project = True

    def _create_github_connection(self):
        repository_auth = self.adbp.create_github_repository_auth(self.organization_name, self.project_name)
        return repository_auth

    def _get_build_by_id(self, organization_name, project_name, build_id):
        builds = self.adbp.list_build_objects(organization_name, project_name)
        return next((build for build in builds if build.id == build_id))


class CmdSelectors(object):

    def __init__(self, cmd, logger):
        self.cmd = cmd
        self.logger = logger

    def cmd_functionapp(self, functionapp_name):
        functionapps = list_function_app(self.cmd)
        functionapp_match = [functionapp for functionapp in functionapps
                             if functionapp.name == functionapp_name]
        if len(functionapp_match) != 1:
            self.logger.error("""Error finding functionapp. Please check that the functionapp exists using 'az functionapp list'""")
            exit(1)
        else:
            functionapp = functionapp_match[0]
        return functionapp

    def cmd_organization(self, organization_name):
        organizations = self.adbp.list_organizations()
        organization_match = [organization for organization in organizations.value
                              if organization.accountName == organization_name]
        if len(organization_match) != 1:
            #TODO need to fix this error message if I am getting rid of the other commands
            self.logger.error("""Error finding organization. Please check that the organization exists using 'functionapp devops-build organization list'""")
            exit(1)
        else:
            organization = organization_match[0]
        return organization

    def cmd_project(self, organization_name, project_name):
        #validate that the project exists
        projects = self.adbp.list_projects(organization_name)
        project_match = \
            [project for project in projects.value if project.name == project_name]

        if len(project_match) != 1:
            #TODO need to fix this error message if I am getting rid of the other commands
            self.logger.error("Error finding project. Please check that the project exists using 'functionapp devops-build project list'")
            exit(1)
        else:
            project = project_match[0]
        return project
