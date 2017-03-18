#!/usr/bin/python
#
# Copyright 2017 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import os
import sys
import yaml

from github import Github
from github.Gist import Gist
from github.InputFileContent import InputFileContent

from generate_bom import BomGenerator
from spinnaker.run import run_quick

SERVICES = 'services'
VERSION = 'version'

COMPONENTS = [
  'clouddriver',
  'deck',
  'echo',
  'front50',
  'gate',
  'igor',
  'orca',
  'rosco',
  'fiat',
  'spinnaker-monitoring',
  'spinnaker'
]

class BomPublisher(BomGenerator):

  def __init__(self, options):
    self.__rc_version = options.rc_version
    self.__bom_dict = {}
    self.__release_version = options.release_version
    self.__github_publisher = options.github_publisher
    self.__changelog_file = options.changelog_file
    self.__github_token = options.github_token
    self.__gist_user = options.gist_user
    super(BomPublisher, self).__init__(options)

  def __unpack_bom(self):
    """Load the release candidate BOM into memory.
    """
    bom_yaml_string = run_quick('hal versions bom {0} --color false'
                                .format(self.__rc_version), echo=False).stdout.strip()
    print bom_yaml_string
    self.__bom_dict = yaml.load(bom_yaml_string)
    print self.__bom_dict

  def publish_release_bom(self):
    """Read, update, and publish a release candidate BOM.
    """
    self.__unpack_bom()
    new_bom_file = '{0}.yml'.format(self.__release_version)
    self.__bom_dict[VERSION] = self.__release_version
    self.write_bom_file(new_bom_file, self.__bom_dict)
    self.publish_bom(new_bom_file)
    # Re-write the 'latest' Spinnaker version.
    # TODO(jacobkiefer): Update 'available versions' with Halyard when that feature is ready.
    self.write_bom_file('latest.yml', self.__bom_dict)
    self.publish_bom('latest.yml')

  def publish_changelog_gist(self):
    """Publish the changelog as a github gist.
    """
    g = Github(self.__gist_user, self.__github_token)
    description = 'Changelog for Spinnaker {0}'.format(self.__release_version)
    with open(self.__changelog_file, 'r') as clog:
      raw_content_lines = clog.readlines()
      spinnaker_version = 'Spinnaker {0}\n'.format(self.__release_version)
      raw_content_lines[0] = spinnaker_version
      content = InputFileContent(spinnaker_version + ''.join(raw_content_lines))
      filename = os.path.basename(self.__changelog_file)
      gist = g.get_user().create_gist(True, {filename: content}, description=description)
      print ('Wrote changelog to Gist at https://gist.github.com/{user}/{id}'
             .format(user=self.__gist_user, id=gist.id))

  def push_branch_and_tags(self):
    """Creates a release branch and pushes tags to the microservice repos owned by --github_publisher.

    A private key that has access to --github_publisher's github repos needs added
    to a running ssh-agent on the machine this script will run on:

    > <copy or rsync the key to the vm>
    > eval `ssh-agent`
    > ssh-add ~/.ssh/<key with access to github repos>

    """
    major, minor, patch = self.__release_version.split('.')

    # The stable branch will look like <major>.<minor>.X since nebula
    # enforces restrictions on what branches it does releases from.
    # https://github.com/nebula-plugins/nebula-release-plugin#extension-provided
    stable_branch = '.'.join([major, minor, 'X'])
    for comp in COMPONENTS:
      self.__exit_if_failure('git -C {0} checkout -b {1}'.format(comp, stable_branch),
                             'git checkout')

      version_tag_build = ''
      if comp == 'spinnaker-monitoring':
        version_tag_build = 'version-{0}'.format(self.__bom_dict[SERVICES]['monitoring-daemon'][VERSION])
      else:
        version_tag_build = 'version-{0}'.format(self.__bom_dict[SERVICES][comp][VERSION])

      last_dash = version_tag_build.rindex('-')
      version_tag = version_tag_build[:last_dash]
      repo_to_push = ('git@github.com:{owner}/{comp}.git'
                      .format(owner=self.__github_publisher, comp=comp))
      self.__exit_if_failure(
        'git -C {comp} remote add release {url}'.format(comp=comp, url=repo_to_push),
        'git remote add'
      )
      self.__exit_if_failure(
        'git -C {comp} push release {branch}'.format(comp=comp,  branch=stable_branch),
        'git push branch'
      )
      g = Github(self.__gist_user, self.__github_token)
      repo = g.get_repo('{owner}/{comp}'.format(owner=self.__github_publisher, comp=comp))
      paginated_tags = repo.get_tags()
      tag_names = [tag.name for tag in paginated_tags]
      if version_tag not in tag_names:
        # The tag doesn't exist and we need to push a tag.
        print ('pushing version tag {tag} to {owner}/{comp}'
               .format(tag=version_tag, owner=self.__github_publisher, comp=comp))
        self.__exit_if_failure(
          'git -C {comp} push release {tag}'.format(comp=comp,  tag=version_tag),
          'git push tag'
        )

  def __exit_if_failure(self, command, task_name):
    """Helper function to run_quick a command and exit if it fails.
    """
    result = run_quick(command)
    if result.returncode != 0:
      print "'{0}' command failed with: \n{1}\n exiting...".format(task_name, result.stdout)
      exit(result.returncode)

  @classmethod
  def main(cls):
    parser = argparse.ArgumentParser()
    cls.init_argument_parser(parser)
    options = parser.parse_args()

    bom_publisher = cls(options)
    bom_publisher.publish_release_bom()
    bom_publisher.publish_changelog_gist()
    bom_publisher.push_branch_and_tags()

  @classmethod
  def init_argument_parser(cls, parser):
    """Initialize command-line arguments."""
    parser.add_argument('--changelog_file', default='', required=True,
                        help='The changelog to publish during this publication.')
    parser.add_argument('--github_token', default='', required=True,
                        help="The GitHub user token with scope='gists' to write gists.")
    parser.add_argument('--gist_user', default='', required=True,
                        help="The GitHub user to write gists as.")
    parser.add_argument('--rc_version', default='', required=True,
                        help='The version of the Spinnaker release candidate we are publishing.')
    parser.add_argument('--release_version', default='', required=True,
                        help="The version for the new Spinnaker release. This needs to be of the form 'X.Y.Z'.")
    parser.add_argument('--github_publisher', default='', required=True,
                        help="The owner of the remote repo the branch and tag are pushed to for each component.")
    super(BomPublisher, cls).init_argument_parser(parser)

if __name__ == '__main__':
  sys.exit(BomPublisher.main())
