# Copyright 2021-2023 Facundo Batista
# Licensed under the GPL v3 License
# For further info, check https://github.com/facundobatista/pyempaq

"""Main packer module."""

import argparse
import json
import logging
import pathlib
import shutil
import tempfile
import uuid
import venv
import zipapp
from collections import namedtuple

from pyempaq import __version__
from pyempaq.common import find_venv_bin, logged_exec, ExecutionError
from pyempaq.config_manager import load_config, ConfigError, Config


# setup logging
logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)-5s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

# collected arguments
Args = namedtuple("Args", "project_name basedir entrypoint requirement_files")


def get_pip():
    """Ensure an usable version of `pip`."""
    useful_pip = pathlib.Path("pip3")
    # try to see if it's already installed
    try:
        logged_exec([useful_pip, "--version"])
    except ExecutionError:
        # failed to find a runnable pip, we need to install one
        pass
    else:
        return useful_pip

    # no useful pip found, let's create a virtualenv and use the one inside
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    venv.create(tmpdir, with_pip=True)
    useful_pip = find_venv_bin(tmpdir, "pip3")
    return useful_pip


def prepare_metadata(origdir: pathlib.Path, config: Config):
    """Prepare the meta-data for the future unpacker action.

    Note that all paths in the config are all already validated to exist
    and relative to the base directory (so no "place adaptation" needs
    to happen for the unpacking).
    """
    # store the needed metadata
    logger.debug("Saving metadata from config %s", config)
    metadata = {
        "requirement_files": [str(path) for path in config.requirements],
        "project_name": config.name,
        "exec_default_args": config.exec.default_args,
        "unpack_restrictions": dict(config.unpack_restrictions or {}),
    }
    if config.exec.script is not None:
        metadata["exec_style"] = "script"
        metadata["exec_value"] = str(config.exec.script)
    elif config.exec.module is not None:
        metadata["exec_style"] = "module"
        metadata["exec_value"] = str(config.exec.module)
    elif config.exec.entrypoint is not None:
        metadata["exec_style"] = "entrypoint"
        metadata["exec_value"] = str(config.exec.entrypoint)

    # if dependencies, store them just as another requirement file (save it inside the project,
    # but using an unique name to not overwrite anything)
    if config.dependencies:
        unique_name = f"pyempaq-autoreq-{uuid.uuid4()}.txt"
        extra_deps = origdir / unique_name
        extra_deps.write_text("\n".join(config.dependencies) + "\n")
        metadata["requirement_files"].append(unique_name)

    return metadata


def pack(config):
    """Pack."""
    project_root = pathlib.Path(__file__).parent
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    logger.debug("Working in temp dir %r", str(tmpdir))

    # copy all the project content inside "orig" in temp dir
    origdir = tmpdir / "orig"
    shutil.copytree(config.basedir, origdir)

    # copy the common module
    pyempaq_dir = tmpdir / "pyempaq"
    pyempaq_dir.mkdir()
    common_src = project_root / "common.py"
    common_final_src = tmpdir / "pyempaq" / "common.py"
    shutil.copy(common_src, common_final_src)

    # copy the unpacker as the entry point of the zip
    unpacker_src = project_root / "unpacker.py"
    unpacker_final_main = tmpdir / "__main__.py"
    shutil.copy(unpacker_src, unpacker_final_main)

    # build a dir with the dependencies needed by the unpacker
    logger.debug("Building internal dependencies dir")
    venv_dir = tmpdir / "venv"
    pip = get_pip()
    cmd = [pip, "install", "appdirs", f"--target={venv_dir}"]
    logged_exec(cmd)

    metadata = prepare_metadata(origdir, config)
    metadata_file = tmpdir / "metadata.json"
    with metadata_file.open("wt", encoding="utf8") as fh:
        json.dump(metadata, fh)

    # create the zipfile
    packed_filepath = f"{config.name}.pyz"
    zipapp.create_archive(tmpdir, packed_filepath)

    # clean the temporary directory
    shutil.rmtree(tmpdir)

    logger.info("Done, project packed in %r", str(packed_filepath))


def main():
    """Manage CLI interaction and call pack."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source", type=pathlib.Path,
        help="The source file (pyempaq.yaml) or the directory where to find it.")
    parser.add_argument(
        '-v', '--verbose',
        help="Show detailed information, typically of interest only when diagnosing problems.",
        action="store_const", dest="loglevel", const=logging.DEBUG)
    parser.add_argument(
        '-q', '--quiet',
        help="Only events of WARNING level and above will be tracked.",
        action="store_const", dest="loglevel", const=logging.WARNING)
    parser.add_argument(
        '-V', '--version',
        help="Print the version and exit.",
        action="version", version=__version__)
    args = parser.parse_args()

    if args.loglevel is not None:
        logging.getLogger().setLevel(args.loglevel)

    try:
        logger.info("Parsing configuration in %r", str(args.source))
        config = load_config(args.source)
    except ConfigError as err:
        logger.error(err)
        for err in err.errors:
            logger.error(err)
        exit(1)
    pack(config)
