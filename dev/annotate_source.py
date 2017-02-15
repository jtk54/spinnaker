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
import logging
import os
import re
import sys

from distutils.version import LooseVersion

from refresh_source import Refresher
from spinnaker.run import run_quick


class CommitTag:
  """Provides a model class to capture the output of 'git show-ref --tags'.

  We also capture the tag versions using `distutils.version` for easy semantic
  version comparison for sorting.
  """
  def __init__(self, ref_line):
    # ref_line is in the form "$commit_hash refs/tags/$tag"
    tokens = ref_line.split(' ')
    self.__hash = tokens[0]
    tag_parts = tokens[1].split('/')
    self.__tag = tag_parts[len(tag_parts) - 1]
    self.__version = LooseVersion(self.__tag)

  def __repr__(self):
    return 'hash: %s, tag: %s, version: %s' % (self.__hash, self.__tag, self.__version)

  @property
  def hash(self):
    return self.__hash

  @property
  def tag(self):
    return self.__tag

  @property
  def version(self):
    return self.__version


class CommitMessage:
  """Provides a model class to capture the output of 'git log --pretty'.
  """
  def __init__(self, hash, msg):
    self.__hash = hash
    self.__msg = msg

  def __repr__(self):
    return 'hash: %s, message: %s' % (self.__hash, self.__msg)

  @property
  def hash(self):
    return self.__hash

  @property
  def msg(self):
    return self.__msg

class VersionBump:
  """Provides a model for a semantic version bump.
  """
  def __init__(self, version_str, major=False, minor=False, patch=False):
    self.__version_str = version_str
    self.__major = major
    self.__minor = minor
    self.__patch = patch

  def __repr__(self):
    return 'version_str: %s, major: %s, minor: %s, patch: %s' % (self.version_str,
                                                                 self.major,
                                                                 self.minor,
                                                                 self.patch)

  def __eq__(self, other):
    return (self.version_str == other.version_str
            and self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch)

  @property
  def version_str(self):
    return self.__version_str

  @property
  def major(self):
    return self.__major

  @property
  def minor(self):
    return self.__minor

  @property
  def patch(self):
    return self.__patch


class GitTagMissingException(Exception):
  """Exception for misconfigured git tags in the operating repository."""
  def __init__(self, message):
    self.message = message


class Annotator(Refresher):
  """Provides semantic version tagging for Spinnaker repositories.

  Each Spinnaker repository has tags that denote releases. These tags follow
  semantic versioning. At the present time, there are two sets of tags in use
  for the Spinnaker repositories: 'vX.Y.Z' for Netflix releases and 'version-X.Y.Z-$build'
  for Spinnaker product releases. This class handles annotations of the
  'version-X.Y.Z-$build' pattern.

  This class provides support for resolving semantic version tags
  based on commit messages and annotating local source trees with the
  tagging information. It is assumed that the commit messages follow
  conventional-changelog commit message conventions. This class also provides
  support for creating release branches and pushing to and pulling from remote
  repositories through extending the Refresher class.
  """

  # regex for 'version-X.Y.Z' versions
  TAG_MATCHER = re.compile('^version-[0-9]+\.[0-9]+\.[0-9]+$')

  def __init__(self, options):
    self.__next_tag = options.next_tag
    self.__path = options.path
    self.__initial_branch = options.initial_branch
    self.__stable_branch = options.stable_branch
    self.__build_number = options.build_number or os.environ.get('BUILD_NUMBER', '')
    self.__force_rebuild = options.force_rebuild
    self.__tags_to_delete = []
    self.__filtered_tags = []
    self.__current_version = None
    self.__partition_tags_on_pattern()
    self.__determine_current_version()
    super(Annotator, self).__init__(options)

  def __partition_tags_on_pattern(self):
    """Partitions the tags into two lists based on TAG_MATCHER.

    One of the lists of tags will be deleted locally (self.__tags_to_delete) so
    gradle will use our tag version as the package version during the
    build/publish task.

    One of the lists will be used to determine the next semantic version
    for out tag pattern (self.__filtered_tags).
    """
    tag_ref_result = run_quick('git -C {path} show-ref --tags'
                                   .format(path=self.__path),
                               echo=False)
    ref_lines = tag_ref_result.stdout.strip().split('\n')
    hash_tags = [CommitTag(s) for s in ref_lines]
    self.__filtered_tags = [ht for ht in hash_tags if self.TAG_MATCHER.match(ht.tag)]
    self.__tags_to_delete = [ht for ht in hash_tags if not self.TAG_MATCHER.match(ht.tag)]

  def tag_head(self):
    """Tags the current branch's HEAD with the next semver tag.
    """
    if self.__is_head_current():
      if self.__force_rebuild:
        self.__tag_head_with_build(self.__current_version.tag)
      else:
        logging.warn("There is already a tag of the form 'version-X.Y.Z' at HEAD. Not forcing rebuild.")
        return
    else:
      version_bump = self.determine_new_tag()
      # This tag is for logical identification for developers. This will be pushed
      # to the upstream git repository if we choose to use this version in a
      # formal Spinnaker product release.
      run_quick('git -C {path} tag {next_tag} HEAD'
                .format(path=self.__path, next_tag=version_bump.version_str))
      self.__tag_head_with_build(version_bump.version_str)

  def __tag_head_with_build(self, version_bump_tag):
    """Tags the current branch's HEAD with the next semver gradle build tag.

    Args:
      version_bump [VersionBump]: Semver to add as a gradle build tag.
    """
    next_tag_with_build = '{0}-{1}'.format(version_bump_tag,
                                           self.__build_number)
    # This tag is for gradle to use as the package version. It incorporates the
    # build number for uniqueness when publishing. This tag is of the form
    # 'X.Y.Z-$build_number' for gradle to use correctly. This is not pushed
    # to the upstream git repository.
    first_dash_idx = next_tag_with_build.index('-')
    gradle_version = next_tag_with_build[first_dash_idx + 1:]
    run_quick('git -C {path} tag {next_tag} HEAD'
              .format(path=self.__path, next_tag=gradle_version))

  def delete_unwanted_tags(self):
    """Locally deletes tags that don't match TAG_MATCHER.

    This is so that gradle will use the latest resolved semantic version from
    our tag pattern when it builds the package.
    """
    for bad_hash_tag in self.__tags_to_delete:
      # NOTE: The following command prints output to STDOUT, so we don't
      # explicitly log anything.
      run_quick('git -C {path} tag -d {tag}'
                .format(path=self.__path, tag=bad_hash_tag.tag))

  def create_stable_branch(self):
    """Creates a branch from --initial_branch/HEAD named --stable_branch.
    """
    run_quick('git -C {path} checkout {initial_branch}'
              .format(path=self.__path, initial_branch=self.__initial_branch))
    run_quick('git -C {path} checkout -b {stable_branch}'
              .format(path=self.__path, stable_branch=self.__stable_branch))

  def __is_head_current(self):
    """Checks if the current version is at HEAD.

    Returns:
      [Boolean]: True if the current version tag is on HEAD, else False.
    """
    head_commit_res = run_quick('git -C {path} rev-parse HEAD'
                                    .format(path=self.__path),
                                echo=False)
    head_commit = head_commit_res.stdout.strip()
    return self.__current_version.hash == head_commit

  def __determine_current_version(self):
    """Determines and stores the current (latest) semantic version from
    'version-X.Y.Z' tags.
    """
    sorted_filtered_tags = sorted(self.__filtered_tags,
                                  key=lambda ht: ht.version, reverse=True)
    if len(sorted_filtered_tags) == 0:
      raise GitTagMissingException("No version tags of the form 'version-X.Y.Z'.")

    self.__current_version = sorted_filtered_tags[0]

  def determine_new_tag(self):
    """Determines the next semver tag for the repository at the path.

    If the commit at HEAD is already tagged with a tag matching --tag_regex_str,
    this function is a no-op. Otherwise it determines the semantic version bump
    for the commits since the last tag matching 'version-X.Y.Z' and suggests a new tag
    based on the commit messages. This suggestion can be overridden with
    --next_tag, which will be used if there are any commits after the last
    semver tag matching 'version-X.Y.Z'.

    Returns:
      [VersionBump]: Next semantic version tag to be used, along with what type
      of version bump it was. Version tag is of the form 'version-X.Y.Z'.
    """
    if self.__next_tag:
      return self.__next_tag

    # 'git log' entries of the form '$hash $commit_title'
    log_onelines = run_quick('git -C {path} log --pretty=oneline'.format(path=self.__path),
                             echo=False).stdout.strip().split('\n')
    commit_hashes = [line.split(' ')[0].strip() for line in log_onelines]

    # Full commit messages, including bodies for finding 'BREAKING CHANGE:'.
    msgs = [
      run_quick('git -C {path} log -n 1 --pretty=medium {hash}'.format(path=self.__path, hash=h),
                echo=False).stdout.strip() for h in commit_hashes
    ]

    if len(commit_hashes) != len(msgs):
      raise IOError('Git commit hash list and commit message list are unequal sizes.')

    return self.bump_semver(self.__current_version, commit_hashes, msgs)

  def bump_semver(self, curr_version, commit_hashes, commit_msgs):
    """Determines the semver version bump based on commit messages in 'git log'.

    Uses 'conventional-changelog' format to search for features and breaking
    changes.

    Args:
      curr_version [CommitTag]: Latest 'version-X.Y.Z' tag/commit hash pair
      calcluated by semver sort.

      commit_hashes [String list]: List of ordered commit hashes.

      commit_msgs [String list]: List of ordered, full commit messages.

    Returns:
      [VersionBump]: Next semantic version tag to be used, along with what type
      of version bump it was.
    """
    # Commits are output from 'git log ...' ordered most recent to least.
    commits_iter = iter([CommitMessage(hash, msg) for hash, msg in zip(commit_hashes, commit_msgs)])
    commit = next(commits_iter, None)

    feat_matcher = re.compile('feat\(.*\)*')
    bc_matcher = re.compile('BREAKING CHANGE')
    feature = False
    breaking_change = False

    first_dash_idx = curr_version.tag.index('-')
    if first_dash_idx == -1:
      raise GitTagMissingException("No version tags of the form 'version-X.Y.Z'.")
    major, minor, patch = curr_version.tag[first_dash_idx + 1:].split('.')

    # TODO(jacobkiefer): Fail if changelog conventions aren't followed?
    while commit is not None and commit.hash != curr_version.hash:
      msg_lines = commit.msg.split('\n')
      if any([bc_matcher.match(m.strip()) for m in msg_lines]):
        breaking_change = True
        break # Breaking change has the highest precedence.
      if any([feat_matcher.match(m.strip()) for m in msg_lines]):
        feature = True
      commit = next(commits_iter, None)

    if breaking_change == True:
      return VersionBump('version-' + str(int(major) + 1) + '.0.0', major=True)
    elif feature == True:
      return VersionBump('version-' + major + '.' + str(int(minor) + 1) + '.0',
                         minor=True)
    else:
      return VersionBump('version-' + major + '.' + minor + '.' + str(int(patch) + 1),
                         patch=True)

  @classmethod
  def init_argument_parser(cls, parser):
    """Initialize command-line arguments."""
    parser.add_argument('--build_number', default='',
                        help='The build number to append to the semantic version tag.')
    parser.add_argument('--initial_branch', default='master',
                        help='Initial branch to create the stable release branch from.')
    parser.add_argument('--next_tag', default='',
                        help='Tag to use as the next tag instead of determining the next semver tag.')
    parser.add_argument('--path', default='.',
                        help='Path to the git repository we want to annotate.')
    parser.add_argument('--stable_branch', default='',
                        help='Name of the stable release branch to create.')
    parser.add_argument('--force_rebuild', default=False, action='store_true',
                        help='Force a rebuild even if there is a git tag at HEAD.')
    super(Annotator, cls).init_argument_parser(parser)

  @classmethod
  def main(cls):
    parser = argparse.ArgumentParser()
    cls.init_argument_parser(parser)
    cls.init_extra_argument_parser(parser)
    options = parser.parse_args()

    annotator = cls(options)
    annotator.tag_head()
    annotator.delete_unwanted_tags()

if __name__ == '__main__':
  sys.exit(Annotator.main())
