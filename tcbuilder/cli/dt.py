import logging
import os
import gi
gi.require_version("OSTree", "1.0")
import traceback
from tcbuilder.errors import TorizonCoreBuilderError
from tcbuilder.backend import dt
from tcbuilder.backend.common import checkout_git_repo
from tcbuilder.errors import PathNotExistError, InvalidStateError
from tcbuilder.backend.overlay_parser import CompatibleOverlayParser

def get_dt_from_list(dt_to_search, dt_list):
    devicetree_bin = None
    for device_tree in dt_list:
        if device_tree["name"] == dt_to_search:
            devicetree_bin = os.path.join(device_tree["path"], device_tree["name"])
            break

    return devicetree_bin

def get_devicetree_bin(devicetree_in, storage_dir, src_ostree_archive_dir):
    dt_list = dt.get_ostree_dtb_list(src_ostree_archive_dir)

    devicetree_bin = None
    if devicetree_in is None:
        # get default 'devicetree' from OSTree
        dt_path = get_dt_from_list("devicetree", dt_list)
        if dt_path is not None:
            devicetree_bin = dt.copy_devicetree_bin_from_ostree(storage_dir, dt_path)

    elif os.path.sep in devicetree_in:
        # search in working dir
        if os.path.exists(os.path.abspath(devicetree_in)):
            devicetree_bin = dt.copy_devicetree_bin_from_workdir(storage_dir,
                                                                 os.path.abspath(devicetree_bin))
        else:
            #search in OSTree
            user_provided_dt = devicetree_in.rsplit('/', 1)[1]
            dt_path = get_dt_from_list(user_provided_dt, dt_list)
            if dt_path:
                devicetree_bin = dt.copy_devicetree_bin_from_ostree(storage_dir, dt_path)
    else:
        # only name is provided
        dt_path = get_dt_from_list(devicetree_in, dt_list)
        if dt_path:
            devicetree_bin = dt.copy_devicetree_bin_from_ostree(storage_dir, dt_path)

    return devicetree_bin

def dt_overlay_subcommand(args):
    log = logging.getLogger("torizon." + __name__)  # use name hierarchy for "main" to be the parent

    if args.overlays is None:
        log.error('No overlay is provided.')
        return

    # create list of available device trees in OSTree
    storage_dir = os.path.abspath(args.storage_directory)
    src_ostree_archive_dir = os.path.join(storage_dir, "ostree-archive")

    devicetree_bin = get_devicetree_bin(args.devicetree_bin,
                                        storage_dir,
                                        src_ostree_archive_dir)
    if devicetree_bin is None:
        log.error(f'No devicetree binary found and the provided device tree {args.devicetree_bin} does not exist. Please specify a device tree.')
        dt_list_devicetrees_subcommand(args)
        return

    devicetree_out = ""
    if args.devicetree_out is not None:
        dt_out = os.path.abspath(args.devicetree_out)
        if not os.path.exists(dt_out):
            log.error(f"{args.devicetree_out} does not exist")
            return
        if os.path.exists(os.path.join(dt_out, "usr")):
            log.error(f"{args.devicetree_out} is not empty")
            return

    devicetree_out = dt.create_dt_changes_dir(args.devicetree_out, args.storage_directory)

    if args.include_dir:
        include_dir = args.include_dir
    else:
        include_dir = dt.get_default_include_dir(src_ostree_archive_dir)

    dt.build_and_apply(devicetree_bin, args.overlays, devicetree_out,
                       include_dir)

    if os.path.exists(os.path.join(storage_dir, "tmp_devicetree.dtb")):
        os.remove(os.path.join(storage_dir, "tmp_devicetree.dtb"))

    log.info(f"Overlays {args.overlays} successfully applied")

def dt_custom_subcommand(args):
    log = logging.getLogger("torizon." + __name__)  # use name hierarchy for "main" to be the parent

    devicetree_out = ""
    if args.devicetree_out is not None:
        devicetree_out = os.path.abspath(args.devicetree_out)
        if not os.path.exists(devicetree_out):
            raise PathNotExistError(f"{args.devicetree_out} does not exist")
        if os.path.exists(os.path.join(devicetree_out, "usr")):
            raise InvalidStateError(f"{args.devicetree_out} is not empty")

    devicetree_out = dt.create_dt_changes_dir(args.devicetree_out, args.storage_directory)

    if args.include_dir:
        include_dir = args.include_dir
    else:
        storage_dir = os.path.abspath(args.storage_directory)
        src_ostree_archive_dir = os.path.join(storage_dir, "ostree-archive")
        include_dir = dt.get_default_include_dir(src_ostree_archive_dir)

    dt.build_and_apply(args.devicetree, None, devicetree_out,
                       include_dir)

    log.info(f"Device tree {args.devicetree} built successfully")

def dt_checkout_subcommand(args):
    log = logging.getLogger("torizon." + __name__)  # use name hierarchy for "main" to be the parent

    storage_dir = os.path.abspath(args.storage_directory)

    if args.git_repo is None:
        if os.path.exists(os.path.abspath("device-trees")):
            log.error("'device-trees' directory already exists")
            return
    elif args.git_repo is not None:
        if args.git_branch is None:
            log.error("git branch is not provided")
            return
        elif (args.git_repo.startswith("https://") or
            args.git_repo.startswith("git://")):
            repo_name = args.git_repo.rsplit('/', 1)[1].rsplit('.', 1)[0]
            if os.path.exists(os.path.abspath(repo_name)):
                log.error(f"directory '{repo_name}' named as repo name should not exist")
                return
        elif not os.path.exists(os.path.abspath(args.git_repo)):
            log.error(f"{args.git_repo} directory does not exist")
            return

    try:
        checkout_git_repo(storage_dir, args.git_repo, args.git_branch)
        log.info("dt checkout completed successfully")
    except TorizonCoreBuilderError as ex:
        log.error(ex.msg)  # msg from all kinds of Exceptions
        if ex.det is not None:
            log.info(ex.det)  # more elaborative message
        log.debug(traceback.format_exc())  # full traceback to be shown for debugging only

def dt_list_overlays_subcommand(args):
    log = logging.getLogger("torizon." + __name__)  # use name hierarchy for "main" to be the parent

    devicetree_bin = None
    if args.devicetree_source is None:
        # Try to detect a default devicetree binary
        storage_dir = os.path.abspath(args.storage_directory)
        src_ostree_archive_dir = os.path.join(storage_dir, "ostree-archive")
        devicetree_bin = get_devicetree_bin(args.devicetree_bin,
                                            storage_dir,
                                            src_ostree_archive_dir)
        if devicetree_bin is None:
            log.error(f'No devicetree binary found and the provided device tree {args.devicetree_bin} does not exist. Please specify a device tree.')
            dt_list_devicetrees_subcommand(args)
            return
    else:
        if not os.path.exists(os.path.abspath(args.devicetree_source)):
            log.error(f"{args.devicetree_source} does not exist")
            return

    if args.overlays_dir is None:
        overlays_path = os.path.abspath("device-trees/overlays")
    else:
        overlays_path = os.path.abspath(args.overlays_dir)

    if not os.path.exists(overlays_path):
        log.error(f"overlays-dir ({overlays_path}) does not exist.\
                  Do a dt checkout or provide a valid overlays-dir.")
        return

    compatibilities = []
    if devicetree_bin is not None:
        compatibilities = dt.get_compatibilities_binary(devicetree_bin)
    else:
        parser = CompatibleOverlayParser(args.devicetree_source)
        compatibilities = parser.get_compatibilities_source()

    compatible_overlays = []
    for path in sorted(os.listdir(overlays_path)):
        # Only consider device tree overlay source files
        if not path.endswith(".dts"):
            continue

        overlay_path = os.path.join(overlays_path, path)
        if not os.path.isfile(overlay_path):
            continue

        # Get "compatible" of overlay and check against base device tree
        parser = CompatibleOverlayParser(overlay_path)
        overlay_compatibilities = parser.get_compatibilities_source()
        if CompatibleOverlayParser.check_compatibility(compatibilities, overlay_compatibilities):
            compatible_overlays.append({ 'path': os.path.relpath(overlay_path),
                                        'description': parser.get_description() } )

    if compatible_overlays:
        log.info("Available overlays are:")
        for compatible_overlay in compatible_overlays:
            log.info(f"\t{compatible_overlay['path']}:")
            log.info(f"\t\t{compatible_overlay['description']}")
    else:
        log.info("No compatible overlay found")

def dt_list_devicetrees_subcommand(args):
    log = logging.getLogger("torizon." + __name__)  # use name hierarchy for "main" to be the parent

    storage_dir = os.path.abspath(args.storage_directory)
    src_ostree_archive_dir = os.path.join(storage_dir, "ostree-archive")

    dt_list = dt.get_ostree_dtb_list(src_ostree_archive_dir)

    log.info("Available device trees in the OSTree are:")
    for item in dt_list:
        log.info(f"\t {item['name']}")

def add_overlay_parser(parser):
    subparsers = parser.add_subparsers(title='Commands:', required=True, dest='cmd')
    subparser = subparsers.add_parser("overlay", help="Apply an overlay")
    subparser.add_argument("--devicetree", dest="devicetree_bin",
                           help="Path to the devicetree binary")
    subparser.add_argument("--devicetree-out", dest="devicetree_out",
                           help="""Path to the devicetree output directory. Defaults to internal
                           storage directory. Device tree file is stored with name 'devicetree'.""")
    subparser.add_argument("--include-dir", dest="include_dir", action='append',
                           help="""Directory with device tree include (.dtsi) or
                           header files. Can be passed multiple times. Defaults to
                           device-trees/include/ and device-trees/dts-[arch]/.""")
    subparser.add_argument(metavar="OVERLAY", dest="overlays", nargs="+",
                           help="The overlay(s) to apply")

    subparser.set_defaults(func=dt_overlay_subcommand)

    subparser = subparsers.add_parser("custom", help="Compile device tree")
    subparser.add_argument("--devicetree-source", dest="devicetree",
                           help="Path to the device tree source file",
                           required=True)
    subparser.add_argument("--devicetree-out", dest="devicetree_out",
                           help="""Path to the devicetree output directory.
                           Device tree file is stored with name 'devicetree'.""")
    subparser.add_argument("--include-dir", dest="include_dir", action='append',
                           help="""Directory with device tree include (.dtsi) or
                           header files. Can be passed multiple times. Defaults to
                           device-trees/include/ and device-trees/dts-[arch]/.""")

    subparser.set_defaults(func=dt_custom_subcommand)

    subparser = subparsers.add_parser("checkout",
                                      help="""Checkout device tree source, overlays and include
                                      files.""")
    subparser.add_argument("--repository", dest="git_repo",
                           help="""Remote repository URL. Default repo is
                           https://github.com/toradex/device-trees""")
    subparser.add_argument("--branch", dest="git_branch",
                           help="""Branch to be checked out. Default branch with default repo is
                           toradex_<kmajor>.<kminor>.<x>""")

    subparser.set_defaults(func=dt_checkout_subcommand)

    subparser = subparsers.add_parser("list-overlays", help="List compatible device tree overlays")
    subparser.add_argument("--devicetree-source", dest="devicetree_source",
                           help="Device tree source file")
    subparser.add_argument("--devicetree", dest="devicetree_bin",
                           help="Device tree binary file")
    subparser.add_argument("--overlays-dir", dest="overlays_dir",
                           help="Path to overlays directory")

    subparser.set_defaults(func=dt_list_overlays_subcommand)
    subparser = subparsers.add_parser("list-devicetrees",
                                      help="List available device trees binaries in OSTree image")

    subparser.set_defaults(func=dt_list_devicetrees_subcommand)

def init_parser(subparsers):
    subparser = subparsers.add_parser("dt", help="""\
    Compile and apply device trees and device tree overlays.
    """)

    add_overlay_parser(subparser)
