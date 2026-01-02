"""
Backend for the splash command
"""

import logging
import os
import shutil
import subprocess
import shlex

from gi.repository import Gio
from tcbuilder.backend.kernel import get_kernel_subdir

SPLASH_INITRAMFS = "initramfs.splash"
INITRAMFS_FILENAME = "initramfs.img"

log = logging.getLogger("torizon." + __name__)


def get_initramfs_subdir(storage_dir):
    """Get the versioned initramfs directory.

    In an OSTree deployment the initramfs is located in the same directory tree
    as the kernel, so we just return the kernel location.
    """

    return get_kernel_subdir(storage_dir)


def get_splash_changes_dir(storage_dir):
    """Returns the directory that contains external splash screen related changes."""

    return os.path.join(storage_dir, "splash")


def merge_splash_initramfs(work_dir, image, src_initramfs, storage_dir):
    """Create a initramfs with a splash screen and append it to a copy of src_initramfs

    The final initramfs binary will be created inside work_dir, following the
    directory tree given by get_initramfs_subdir()
    """

    splash_initramfs_dir = "usr/share/plymouth/themes/spinner/"
    rel_splash_initramfs_dir = os.path.join(work_dir, splash_initramfs_dir)  # relative to work_dir

    os.makedirs(rel_splash_initramfs_dir, exist_ok=True)
    shutil.copy(image, os.path.join(rel_splash_initramfs_dir, "watermark.png"))

    # Currently there is no official library for python 3+ to create
    # cpio archive. So bash commands are to be used

    # create splash image only initramfs
    create_initramfs_cmd = "echo {0} | cpio -H newc -D {1} -o | gzip > {2}".format(
        shlex.quote(os.path.join(splash_initramfs_dir, "watermark.png")),
        shlex.quote(work_dir), shlex.quote(os.path.join(work_dir, SPLASH_INITRAMFS)))
    subprocess.check_output(create_initramfs_cmd, shell=True, stderr=subprocess.STDOUT)

    # Create final initramfs in ${work_dir}/${dir_tree}/${INITRAMFS_FILENAME}
    dir_tree = get_initramfs_subdir(storage_dir)
    os.makedirs(os.path.join(work_dir, dir_tree), exist_ok=True)

    merged_initramfs_path = os.path.join(work_dir, dir_tree, INITRAMFS_FILENAME)
    initramfs = Gio.File.new_for_path(merged_initramfs_path).create(Gio.FileCreateFlags.NONE, None)

    # Add src_initramfs and splash image to final file
    # src_initramfs > ${work_dir}/${dir_tree}/${INITRAMFS_FILENAME}
    initramfs.splice(Gio.File.new_for_path(src_initramfs).read(None),
                     Gio.OutputStreamSpliceFlags.CLOSE_SOURCE, None)
    # ${work_dir}/initrmafs.splash > ${work_dir}/${dir_tree}/${INITRAMFS_FILENAME}
    initramfs.splice(Gio.File.new_for_path(os.path.join(work_dir, SPLASH_INITRAMFS)).read(None),
                     Gio.OutputStreamSpliceFlags.CLOSE_SOURCE |
                     Gio.OutputStreamSpliceFlags.CLOSE_TARGET, None)

    os.remove(os.path.join(work_dir, SPLASH_INITRAMFS))
    return merged_initramfs_path
