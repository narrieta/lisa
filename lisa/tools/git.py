# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import pathlib
import re
from typing import List

from assertpy import assert_that
from semver import VersionInfo

from lisa.executable import Tool
from lisa.operating_system import Posix, Suse
from lisa.util import LisaException, constants, filter_ansi_escape, get_matched_str


class CodeExistsException(LisaException):
    ...


class Git(Tool):
    CODE_FOLDER_PATTERN = re.compile(r"Cloning into '(.+)'")
    CODE_FOLDER_ON_EXISTS_PATTERN = re.compile(
        r"destination path '(?P<path>.*?)' already exists "
        r"and is not an empty directory.",
        re.M,
    )
    CERTIFICATE_ISSUE_PATTERN = re.compile(
        r"server certificate verification failed", re.M
    )
    VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")

    @property
    def command(self) -> str:
        return "git"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, Suse):
            self.node.os.install_packages("git-core")
        elif isinstance(self.node.os, Posix):
            self.node.os.install_packages([self])
        else:
            raise LisaException(
                "Doesn't support to install git in Windows. "
                "Make sure git is installed and in PATH"
            )
        return self._check_exists()

    def clone(
        self,
        url: str,
        cwd: pathlib.PurePath,
        ref: str = "",
        dir_name: str = "",
        fail_on_exists: bool = True,
    ) -> pathlib.PurePath:
        self.node.shell.mkdir(cwd, exist_ok=True)

        cmd = f"clone {url} {dir_name} --recurse-submodules"
        # git print to stderr for normal info, so set no_error_log to True.
        result = self.run(cmd, cwd=cwd, no_error_log=True)
        if get_matched_str(result.stdout, self.CERTIFICATE_ISSUE_PATTERN):
            self.run("config --global http.sslverify false")
            result = self.run(cmd, cwd=cwd, no_error_log=True, force_run=True)

        # mark directory safe
        self._mark_safe(cwd)

        if result.exit_code == 0:
            output = result.stderr
            if not output:
                output = result.stdout
            code_dir = get_matched_str(output, self.CODE_FOLDER_PATTERN)
        else:
            stdout = result.stdout
            code_dir = get_matched_str(stdout, self.CODE_FOLDER_ON_EXISTS_PATTERN)
            if code_dir:
                if fail_on_exists:
                    raise CodeExistsException(f"code or folder exists. {stdout}")
                else:
                    self._log.debug(f"path '{code_dir}' exists, clone skipped.")
            else:
                raise LisaException(f"failed to clone the repo. {stdout}")
        full_path = cwd / code_dir
        self._log.debug(f"code path: {full_path}")
        if ref:
            self.checkout(ref, cwd=full_path)
        return full_path

    def checkout(
        self, ref: str, cwd: pathlib.PurePath, checkout_branch: str = ""
    ) -> None:
        if not checkout_branch:
            # create a temp branch to checkout tag or commit.
            checkout_branch = f"{constants.RUN_ID}"

        # force run to make sure checkout among branches correctly.
        result = self.run(
            f"checkout {ref} -b {checkout_branch}",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )
        # to output the stdout to log, so it's not integrated with above line.
        result.assert_exit_code(message=f"failed to checkout branch. {result.stdout}")

        # in case there is submodule.
        self.run(
            "submodule update",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
        )

    def discard_local_changes(self, cwd: pathlib.PurePath) -> None:
        result = self.run("checkout .", force_run=True, cwd=cwd, no_error_log=True)
        result.assert_exit_code(
            message=f"failed to discard local changes. {result.stdout}"
        )

    def pull(self, cwd: pathlib.PurePath) -> None:
        result = self.run(
            "pull",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(message=f"failed to pull code. {result.stdout}")

    def fetch(self, cwd: pathlib.PurePath) -> None:
        result = self.run(
            "fetch -p",
            force_run=True,
            cwd=cwd,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(message=f"failed to fetch code. {result.stdout}")

    def apply(
        self,
        cwd: pathlib.PurePath,
        patches: pathlib.PurePath,
    ) -> None:
        result = self.run(
            f"apply {patches}",
            shell=True,
            cwd=cwd,
            force_run=True,
            no_info_log=True,
            no_error_log=True,
        )
        result.assert_exit_code(message=f"failed on applying patches. {result.stdout}")

    def list_tags(self, cwd: pathlib.PurePath) -> List[str]:
        result = self.run(
            "--no-pager tag --color=never",
            shell=True,
            cwd=cwd,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not fetch tags from git repo.",
        )
        return filter_ansi_escape(result.stdout).splitlines()

    def list_commit_ids(self, cwd: pathlib.PurePath) -> List[str]:
        result = self.run(
            "--no-pager log --pretty=format:%h",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch commit ids.",
        )
        return filter_ansi_escape(result.stdout).splitlines()

    def get_latest_commit_id(self, cwd: pathlib.PurePath) -> str:
        result = self.run(
            "--no-pager log -n 1 --pretty=format:%h",
            shell=True,
            cwd=cwd,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to fetch latest commit id.",
        )
        return filter_ansi_escape(result.stdout)

    def init_submodules(self, cwd: pathlib.PurePath) -> None:
        self.run(
            "submodule update --init",
            shell=True,
            cwd=cwd,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on init submodules.",
        )

    def get_tag(
        self,
        cwd: pathlib.PurePath,
        sort_by: str = "v:refname",
        contains: str = "",
        return_last: bool = True,
        filter: str = "",
    ) -> str:
        sort_arg = ""
        contains_arg = ""
        # git tag sort was not added until 2.36.1 in 2015
        # https://github.com/git/git/commit/b7cc53e92c806b73e14b03f60c17b7c29e52b4a4

        # git tag exposes various sort options, apply them if present
        # default is sort by version, ascending
        if sort_by:
            sort_arg = f"--sort={sort_by}"
        if contains:
            # git tag allows you to filter by a commit id, apply it is present.
            contains_arg = f"--contains {contains}"

        if self.get_version() >= VersionInfo.parse("2.36.1") or not sort_arg:
            git_cmd = f"--no-pager tag {sort_arg} {contains_arg}"
        else:
            # version is less than 2.36 and sorting is desired
            # ask git to list tags and sort with sort -V
            git_cmd = f" --no-pager tag -l {contains_arg} | sort -V"

        tags = self.run(
            git_cmd,
            cwd=cwd,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "git tag failed to fetch tags, "
                "check sort and commit arguments are correct"
            ),
        ).stdout.splitlines()
        if filter:
            filter_re = re.compile(filter)
            tags = [x for x in tags if filter_re.search(x)]

        # build some nice error info for failure cases
        error_info = f"sortby:{sort_by} contains:{contains}"
        if filter:
            error_info += f" filter:{filter}"
        assert_that(len(tags)).described_as(
            "Error: could not find any tags with this sort or "
            f"filter setting: {error_info}"
        ).is_greater_than(0)

        if return_last:
            return tags[-1]
        else:
            return tags[0]

    def get_version(self) -> VersionInfo:
        result = self.run("--version")
        version_str = get_matched_str(result.stdout, self.VERSION_PATTERN)
        return VersionInfo.parse(version_str)

    def _mark_safe(self, cwd: pathlib.PurePath) -> None:
        self.run(f"config --global --add safe.directory {cwd}", cwd=cwd)
