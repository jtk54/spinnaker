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
import base64
import os
import sys
import urllib2
import yaml

from spinnaker.run import run_quick

SUBSYSTEMS = ['clouddriver', 'orca', 'front50',
              'echo', 'rosco', 'gate', 'igor', 'fiat', 'deck']
ADDITIONAL_SUBSYSTEMS = ['spinnaker-monitoring']
SERVICES = 'services'
VERSION = 'version'

class PackagePromoter(object):

  def __init__(self, options):
    self.__bom_dict = {}
    self.__test_org = options.test_org
    self.__test_repo = options.test_repo
    self.__prod_org = options.prod_org
    self.__prod_repo = options.prod_repo
    self.__spinnaker_version = options.spinnaker_version
    self.__verify_bintray()

  def promote_debs(self):
    self.__unpack_bom()
    for comp in SUBSYSTEMS:
      self.__get_deb(comp, self.__bom_dict[SERVICES][comp][VERSION])

  def __unpack_bom(self):
    # TODO(jacobkiefer): Replace this command with hal.
    bom_yaml_string = run_quick('cat 0.3.0-184.yml', echo=False).stdout.strip()
    print bom_yaml_string
    self.__bom_dict = yaml.load(bom_yaml_string)
    print self.__bom_dict

  def __get_deb(self, component, version):
    bintray_key = os.environ['BINTRAY_KEY']
    bintray_user = os.environ['BINTRAY_USER']
    deb_name = 'spinnaker-{comp}_{version}_all.deb'.format(comp=component,
                                                           version=version)
    path = ('pool/main/s/spinnaker-{comp}/{deb}'
            .format(comp=component, version=version, deb=deb_name))
    get_url = ('https://{subject}.bintray.com/{repo}/{path}'
               .format(subject=self.__test_org, repo=self.__test_repo, path=path))

    print 'Fetching {deb} from {subject}/{repo}...'.format(deb=deb_name,
                                                        subject=self.__test_org,
                                                        repo=self.__test_repo)
    get_request = urllib2.Request(get_url)
    encoded_auth = base64.encodestring('{user}:{pwd}'
                                       .format(user=bintray_user, pwd=bintray_key))[:-1]  # strip eoln
    get_request.add_header('Authorization', 'Basic ' + encoded_auth)
    get_request.get_method = lambda: 'GET'
    try:
      result = urllib2.urlopen(get_request)
      with open(deb_name, 'w') as deb_file:
        deb_file.write(result.read())
    except Exception as e:
      print 'Received {e} when fetching package.'.format(e=e)


  def __promote_deb(self, component, version):
    bintray_key = os.environ['BINTRAY_KEY']
    bintray_user = os.environ['BINTRAY_USER']
    package = 'spinnaker-{comp}'.format(comp=component)
    deb_name = 'spinnaker-{comp}_{version}_all.deb'.format(comp=component,
                                                           version=version)
    path = ('pool/main/s/spinnaker-{comp}/{deb}'
            .format(comp=component, version=version, deb=deb_name))
    put_url = ('https://api.bintray.com/content/{subject}/{repo}/{package}/{version}/{path}'
               .format(subject=self.__test_org, repo=self.__test_repo,
                       package=package, version=version, path=path))

    print 'Publishing {deb} at {version} to {subject}/{repo}...'.format(deb=deb_name,
                                                                        version=version,
                                                                        subject=self.__test_org,
                                                                        repo=self.__test_repo)
    put_request = urllib2.Request(put_url)
    encoded_auth = base64.encodestring('{user}:{pwd}'
                                       .format(user=bintray_user, pwd=bintray_key))[:-1]  # strip eoln
    put_request.add_header('Authorization', 'Basic ' + encoded_auth)
    # TODO(jacobkiefer): Add deb stuff as headers.
    put_request.get_method = lambda: 'PUT'
    try:
      result = urllib2.urlopen(put_request)
    except Exception as e:
      print 'Received {e} when publishing package.'.format(e=e)

  @classmethod
  def init_argument_parser(cls, parser):
    parser.add_argument(
      '--test_org', default='',
      help='The test Bintray debian org the validated Spinnaker packages to promote live in.\n'
      'This requires BINTRAY_USER and BINTRAY_KEY are set.')
    parser.add_argument(
      '--test_repo', default='',
      help='The test Bintray debian repository the validated Spinnaker packages to promote live in.\n'
      'This requires BINTRAY_USER and BINTRAY_KEY are set.')
    parser.add_argument(
      '--prod_org', default='',
      help='The prod Bintray debian org the validated Spinnaker packages are promoted to.\n'
      'This requires BINTRAY_USER and BINTRAY_KEY are set.')
    parser.add_argument(
      '--prod_repo', default='',
      help='The prod Bintray debian repository the validated Spinnaker packages are promoted to.\n'
      'This requires BINTRAY_USER and BINTRAY_KEY are set.')
    parser.add_argument(
      '--spinnaker_version', default='',
      help='The top-level Spinnaker version we are promoting.')

  def __verify_bintray(self):
    if not os.environ.get('BINTRAY_KEY', None):
      raise ValueError('BINTRAY_KEY environment variable not defined')
    if not os.environ.get('BINTRAY_USER', None):
      raise ValueError('BINTRAY_USER environment variable not defined')

  @classmethod
  def main(cls):
    parser = argparse.ArgumentParser()
    cls.init_argument_parser(parser)
    options = parser.parse_args()

    promoter = cls(options)
    promoter.promote_debs()


if __name__ == '__main__':
  sys.exit(PackagePromoter.main())
