"""Bundle CLI frontend

Allows to bundle a Toradex Easy Installer images with a set of containers.
"""

import logging
import os

import dockerbundle
from tcbuilder.backend import common


def bundle_containers(args):
    """\"bundle\" sub-command"""
    # If no Docker host workdir is given, we assume that Docker uses the same
    # path as we do to access the current working directory.
    host_workdir = args.host_workdir
    if host_workdir is None:
        host_workdir = os.getcwd()

    logging.info("Creating Docker Container bundle.")
    dockerbundle.download_containers_by_compose_file(
                args.bundle_directory, args.compose_file, host_workdir,
                platform=args.platform, output_filename=common.DOCKER_BUNDLE_FILENAME)
    logging.info(f"Successfully created Docker Container bundle in {args.bundle_directory}.")


def init_parser(subparsers):
    """Initialize argument parser"""
    subparser = subparsers.add_parser("bundle", help="""\
    Create container bundle from a Docker Compose file. Can be used to combine with
    a TorizonCore base image.
    """)
    subparser.add_argument("-f", "--file", dest="compose_file",
                           help="Specify an alternate compose file",
                           default="docker-compose.yml")
    subparser.add_argument("--platform", dest="platform",
                           help="""Specify platform to make sure fetching the correct
                           container image when multi-platform container images are
                           specified (e.g. linux/arm/v7 or linux/arm64)""",
                           default="linux/arm/v7")
    subparser.add_argument("--host-workdir", dest="host_workdir",
                           help="""Location where Docker needs to bind mount to to
                           share data between this script and the DIND instance.""")
    subparser.set_defaults(func=bundle_containers)