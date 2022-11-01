"""Bundle CLI frontend

Allows to bundle a Toradex Easy Installer images with a set of containers.
"""

import argparse
import logging
import os
import shutil
import re

from tcbuilder.backend import common
from tcbuilder.backend import bundle as bundle_be
from tcbuilder.errors import InvalidArgumentError, InvalidStateError

log = logging.getLogger("torizon." + __name__)

REGISTRY_REGEX = re.compile((r"^((?!.*://).*|"
                             r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})"
                             r"(:[0-9]*)?$"))

# pylint: disable=too-many-arguments
def bundle(bundle_dir, compose_file, force=False, platform=None,
           logins=None, cacerts=None, dind_params=None):
    """Main handler of the bundle command (CLI layer)

    :param bundle_dir: Name of bundle directory (that will be created in the
                       working directory).
    :param compose_file: Relative path to the input compose file.
    :param force: Whether or not to overwrite the (output) bundle directory
                  if it already exists.
    :param platform: Default platform to use when fetching multi-platform
                     container images.
    :param logins: List of logins to perform: each element of the list must
                   be either a 2-tuple: (USERNAME, PASSWORD) or a 3-tuple:
                   (REGISTRY, USERNAME, PASSWORD) or equivalent iterable.
    :param cacerts: List of CAcerts to perform: each element on the list must
                    be a 2-tuple with: (REGISTRY, CERTIFICATE)
    :param dind_params: Extra parameters to pass to Docker-in-Docker (list).
    """

    if os.path.exists(bundle_dir):
        if force:
            log.debug(f"Removing existing bundle directory '{bundle_dir}'")
            shutil.rmtree(bundle_dir)
        else:
            raise InvalidStateError(
                f"Bundle directory '{bundle_dir}' already exists; please remove "
                "it or pass a different output directory name.")

    # Determine mapping between volume and working directory.
    host_workdir = common.get_host_workdir()

    log.info("Creating Docker Container bundle...")

    bundle_be.download_containers_by_compose_file(
        bundle_dir, compose_file, host_workdir, logins,
        output_filename=common.DOCKER_BUNDLE_FILENAME,
        cacerts=cacerts, platform=platform,
        dind_params=dind_params)

    log.info(f"Successfully created Docker Container bundle in \"{bundle_dir}\"!")

# pylint: enable=too-many-arguments


def do_bundle(args):
    """\"bundle\" sub-command"""

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-25).
    if args.host_workdir_compat:
        raise InvalidArgumentError(
            "Error: the switch --host-workdir has been removed; "
            "please run the tool without passing that switch (and its argument).")

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-17).
    if args.compose_file_compat:
        raise InvalidArgumentError(
            "Error: the switch --file (-f) has been removed; "
            "please provide the file name without passing the switch.")

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-17).
    if args.username_compat or args.password_compat or args.registry_compat:
        raise InvalidArgumentError(
            "Error: the switches --docker-username, --docker-password and --registry "
            "have been removed; please use either --login or --login-to.")

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-17).
    if not args.compose_file:
        raise InvalidArgumentError(
            "Error: the COMPOSE_FILE positional argument is required.")

    def check_registry_names(registries):
        if registries is None:
            return
        for registry in registries:
            if not REGISTRY_REGEX.match(registry[0]):
                raise InvalidArgumentError(
                    f"Error: invalid registry specified: '{registry[0]}'; "
                    "the registry can be specified as a domain name or an IP "
                    "address possibly followed by :<port-number>")

    check_registry_names(args.cacerts)
    check_registry_names(args.extra_logins)

    # Build list of logins:
    logins = []
    if args.main_login:
        logins.append(args.main_login)

    if args.extra_logins:
        logins.extend(args.extra_logins)

    bundle(bundle_dir=args.bundle_directory,
           compose_file=args.compose_file,
           force=args.force,
           platform=args.platform,
           logins=logins,
           cacerts=args.cacerts,
           dind_params=args.dind_params)

    common.set_output_ownership(args.bundle_directory)


def init_parser(subparsers):
    """Initialize argument parser"""

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-25).
    subparser = subparsers.add_parser(
        "bundle",
        help=("Create container bundle from a Docker Compose file. Can be "
              "used to combine with a TorizonCore base image."),
        epilog=(
            "NOTE: following switches have been removed: --docker-username, "
            "--docker-password, --registry, --host-workdir and --file (-f); "
            "please review your command line if using any of them."))

    common.add_bundle_directory_argument(subparser)

    # The nargs='?' argument below can be removed together with the
    # --host-workdir and --file switches that currently exist just to allow
    # for better messages (DEPRECATED since 2021-05-17).
    subparser.add_argument(
        nargs='?',
        dest="compose_file",
        help=("Compose file to be processed (REQUIRED); "
              "commonly named 'docker-compose.yml'."))
    subparser.add_argument(
        "--force", dest="force",
        default=False, action="store_true",
        help=("Force program output (remove output directory before starting "
              "the bundle generation process)."))
    subparser.add_argument(
        "--platform", dest="platform",
        help=("Default platform for fetching container images when multi-"
              "platform images are specified in the compose file (e.g. "
              "linux/arm/v7 or linux/arm64)."))
    common.add_common_registry_arguments(subparser)
    subparser.add_argument(
        "--dind-param", action="append", dest="dind_params", metavar="DIND_PARAM",
        help=("Parameter to forward to the Docker-in-Docker container executed by the "
              "tool (can be employed multiple times). The parameter will be processed "
              "by the Docker daemon (dockerd) running in the container. Please see "
              "Docker documentation for more information."))

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-25).
    subparser.add_argument(
        "--host-workdir", dest="host_workdir_compat", help=argparse.SUPPRESS)
    subparser.add_argument(
        "-f", "--file", dest="compose_file_compat", help=argparse.SUPPRESS)
    subparser.add_argument(
        "--docker-username", dest="username_compat", help=argparse.SUPPRESS)
    subparser.add_argument(
        "--docker-password", dest="password_compat", help=argparse.SUPPRESS)
    subparser.add_argument(
        "--registry", dest="registry_compat", help=argparse.SUPPRESS)

    subparser.set_defaults(func=do_bundle)
