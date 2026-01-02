"""
CLI for the splash command
"""

import argparse
import os
import logging

from tcbuilder.errors import \
    (InvalidArgumentError, InvalidDataError, PathNotExistError)
from tcbuilder.backend import splash as splash_be
from tcbuilder.backend import kernel as kernel_be
from tcbuilder.backend.kernelfit import KernelFit
from tcbuilder.backend import ostree
from tcbuilder.backend.common import \
    (get_storage_dir, images_unpack_executed, is_file_type_fit)

log = logging.getLogger("torizon." + __name__)  # use name hierarchy for "main" to be the parent

MAX_INITRAMFS_FILE_SIZE = 32*1024*1024
# Initramfs has the same deploy path as the kernel
OSTREE_INITRAMFS_DEPLOY_PATH = kernel_be.OSTREE_KERNEL_DEPLOY_PATH


def _apply_splash_fit(changes_dir, splash_src, storage_dir):
    """Apply the given splash screen into a changes directory (FIT kernel case)"""

    kernel_path = kernel_be.copy_kernel_to_changes_dir(changes_dir, storage_dir)

    # Load kernel FIT into memory
    with open(kernel_path, "rb") as fhandle:
        fit = KernelFit(fhandle)

    initramfs_name, initramfs_data = fit.extract_default_ramdisk()
    tmp_initramfs_path = os.path.join(changes_dir, initramfs_name)

    # Extract the initramfs from the kernel FIT
    with open(tmp_initramfs_path, "wb") as fhandle:
        fhandle.write(initramfs_data)

    updated_initramfs = splash_be.merge_splash_initramfs(changes_dir, splash_src,
                                                         tmp_initramfs_path, storage_dir)
    # Remove extracted initramfs binary
    os.remove(tmp_initramfs_path)

    with open(updated_initramfs, "rb") as fhandle:
        updated_data = fhandle.read(MAX_INITRAMFS_FILE_SIZE+1)
        if len(updated_data) > MAX_INITRAMFS_FILE_SIZE:
            raise InvalidDataError(
                f"Initramfs file size exceeds limit of {MAX_INITRAMFS_FILE_SIZE} bytes.")

    # Store into FIT.
    log.debug("Updating initramfs with %d bytes in size into FIT image.", len(updated_data))
    fit.update_ramdisk(initramfs_name, updated_data)

    # Update kernel FIT image on disk.
    with open(kernel_path, "wb") as fhandle:
        fit.write(fhandle)
    # Remove updated initramfs binary
    os.remove(updated_initramfs)


def _apply_splash_non_fit(changes_dir, splash_src, storage_dir):
    """Apply the given splash screen into a changes directory (non-FIT case)"""

    # Get path of initramfs of current deployment inside sysroot
    # rootfs dir is assumed to be named 'sysroot'
    sysroot_path = os.path.join(storage_dir, "sysroot")
    sysroot_obj = ostree.load_sysroot(sysroot_path)
    csum, _ = ostree.get_deployment_info_from_sysroot(sysroot_obj)
    kver = ostree.get_kernel_version(sysroot_obj.repo(), csum)

    # Add deployment index part to checksum string, which is 0 for a new deployment
    csum += ".0"
    initramfs_path = OSTREE_INITRAMFS_DEPLOY_PATH.format(csum=csum, kver=kver)
    initramfs_path = os.path.join(sysroot_path, initramfs_path, splash_be.INITRAMFS_FILENAME)

    if os.path.isfile(initramfs_path):
        log.debug("Initramfs found at '%s'", initramfs_path)
    else:
        raise PathNotExistError("Initramfs not found in unpacked rootfs. Aborting.")

    splash_be.merge_splash_initramfs(changes_dir, splash_src, initramfs_path, storage_dir)


def splash(splash_image):
    """Prepare everything to call the "splash" backend service.

    :param splash_image: Path to the image splash filename.
    :raises:
        PathNotExistError: If could not find the splash image file.
    """

    storage_dir = get_storage_dir()
    splash_abspath = os.path.abspath(splash_image)
    if not os.path.isfile(splash_abspath):
        raise PathNotExistError(f"Unable to find splash image {splash_image}")

    unpacked_kernel_path = kernel_be.find_kernel_in_sysroot(storage_dir)
    kernel_is_fit = is_file_type_fit(unpacked_kernel_path)
    log.debug(f"splash: kernel_is_fit={kernel_is_fit}")

    if kernel_is_fit:
         # FIT case: all changes go to the kernel-changes directory.
        changes_dir = kernel_be.get_kernel_changes_dir(storage_dir)
        _apply_splash_fit(changes_dir, splash_abspath, storage_dir)
    else:
        # non-FIT case: changes go to the splash-changes directory.
        changes_dir = splash_be.get_splash_changes_dir(storage_dir)
        _apply_splash_non_fit(changes_dir, splash_abspath, storage_dir)

    log.info("splash screen merged to initramfs")


def do_splash(args):
    """Check for deprecated parameters.

    :param args: Arguments provided to the "isolate" subcommand.
    :raises:
        InvalidArgumentError: If a deprecated switch was passed.
    """

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-17).
    if args.image_compat:
        raise InvalidArgumentError(
            "Error: "
            "the switch --image has been removed; "
            "please provide the image filename without passing the switch.")

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-17).
    if args.work_dir_compat:
        raise InvalidArgumentError(
            "Error: "
            "the switch --work-dir has been removed; "
            "the initramfs file should be created in storage.")

    images_unpack_executed()
    splash(args.splash_image)


def init_parser(subparsers):
    """Parser for "splash" command."""

    subparser = subparsers.add_parser(
        "splash",
        help="change splash screen",
        epilog="NOTE: the switches --image and --work-dir have been removed.",
        allow_abbrev=False)

    subparser.add_argument(
        dest="splash_image",
        metavar="SPLASH_IMAGE",
        help=("Path and name of splash screen image (REQUIRED)."))

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-17).
    subparser.add_argument(
        "--image",
        dest="image_compat",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS)

    # Temporary solution to provide better messages (DEPRECATED since 2021-05-17).
    subparser.add_argument(
        "--work-dir",
        dest="work_dir_compat",
        type=str,
        default="",
        help=argparse.SUPPRESS)

    subparser.set_defaults(func=do_splash)
