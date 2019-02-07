# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class ProjectFailed(object):  # pylint: disable=too-few-public-methods

    def __init__(self, message):
        self.valid = False
        self.message = message
