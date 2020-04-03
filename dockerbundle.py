#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
import time
import docker
import compose.config
import compose.config.environment
import compose.config.serialize
import subprocess
import re
import logging

#
# This class assumes we can use host Docker to create a bundle of the containers
# Note that this is most often not the case as other images are already
# preinstalled...
#
class DockerManager:
    def __init__(self, output_dir):
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)
        self.output_dir = output_dir
        self.output_dir_host = output_dir

    def start(self):
        pass

    def stop(self):
        pass

    def get_tar_command(self, output_file):

        return [ "tar", "--numeric-owner",
                "--preserve-permissions", "--directory=/var/lib/docker",
                "--xattrs-include='*'", "--create", "--file", output_file,
                "overlay2/", "image/" ]

    """
    Get compression command

    Args:
        output_filename: File name or path with compression extension

    Returns:
        (str, str): output_file without compression ending, compression command
    """
    def get_compression_command(self, output_file):
        command = None
        if output_file.endswith(".xz"):
            output_file_tar = output_file[:-3]
            command = [ "xz" , "-3", "-z", output_file_tar ]
        elif output_file.endswith(".gz"):
            output_file_tar = output_file[:-3]
            command = [ "gzip", output_file_tar ]
        elif output_file.endswith(".lzo"):
            output_file_tar = output_file[:-4]
            command = [ "lzop", "-U", "-o", output_file, output_file_tar ]
        elif output_file.endswith(".zst"):
            output_file_tar = output_file[:-4]
            command = [ "zstd", "--rm", output_file_tar, "-o", output_file ]

        return (output_file_tar, command)

    def get_client(self):
        return docker.from_env()

    def save_tar(self, output_file):

        (output_file_tar, compression_command) = self.get_compression_command(output_file)

        # Use host tar to store the Docker storage backend
        subprocess.run(self.get_tar_command(os.path.join(self.output_dir, output_file_tar), check=True))

        output_filepath = os.path.join(self.output_dir, self.output_file)
        if os.path.exists(output_filepath):
            os.remove(output_filepath)
        subprocess.run(compression_command, cwd=self.output_dir, check=True)

class DindManager(DockerManager):
    DIND_CONTAINER_IMAGE = "docker:19.03.8-dind"
    DIND_CONTAINER_NAME = "fetch-dind"
    DIND_VOLUME_NAME = "dind-volume"

    def __init__(self, output_dir, host_workdir):
        super(DindManager, self).__init__(output_dir)
        self.output_dir_host = os.path.join(host_workdir, output_dir)
        cert_dir = os.path.join(os.getcwd(), "certs")
        if not os.path.isdir(cert_dir):
            os.mkdir(cert_dir)
        self.cert_dir_host = os.path.join(host_workdir, "certs")
        self.cert_dir = cert_dir

        self.host_client = docker.from_env()
        self.network = None


    def start(self, network_name="fetch-dind-network", default_platform=None):
        dind_cmd = [ "--storage-driver", "overlay2" ]

        if network_name == "host":
            # Choose a safe and high port to avoid conflict with already
            # running docker instance...
            port = 22376
            dind_cmd.append("--host=tcp://0.0.0.0:{}".format(port))

            if "DOCKER_HOST" in os.environ:
                # In case we use a Docker host, also connect to that host to
                # reach the DIND instance (Gitlab CI case)
                docker_host = os.environ["DOCKER_HOST"]
                results = re.findall("tcp?:\/\/(.*):(\d*)\/?.*", docker_host)
                if not results or len(results) < 1:
                    raise Exception("Regex does not match: {}".format(docker_host))
                self.docker_host = "tcp://{}:{}".format(results[0][0], port)
            else:
                self.docker_host = "tcp://127.0.0.1:{}".format(port)
        else:
            logging.info("Create network {}".format(network_name))
            self.network = self.host_client.networks.create(network_name, driver="bridge")

        self.dind_volume = self.host_client.volumes.create(name=self.DIND_VOLUME_NAME)

        environment = { 'DOCKER_TLS_CERTDIR': '/certs' }
        if default_platform is not None:
            environment['DOCKER_DEFAULT_PLATFORM'] = default_platform
        self.dind_container = self.host_client.containers.run(self.DIND_CONTAINER_IMAGE,
            privileged=True,
            environment=environment,
            volumes= {
                       self.cert_dir_host: {'bind': '/certs/client', 'mode': 'rw'},
                       self.DIND_VOLUME_NAME: {'bind': '/var/lib/docker/', 'mode': 'rw'}
                     },
            network=network_name,
            name=self.DIND_CONTAINER_NAME,
            auto_remove=True,
            detach=True,
            command = dind_cmd)

        time.sleep(10)

        if not network_name == "host":
            # Find IP of the DIND cotainer (make sure attributes are current...)
            self.dind_container.reload()
            dind_ip = self.dind_container.attrs["NetworkSettings"]["Networks"][network_name]["IPAddress"]
            self.docker_host = "tcp://{}:2376".format(dind_ip)

    def stop(self):
        self.dind_container.stop()
        # Otherwise Docker API throws execeptions...
        time.sleep(1)
        self.dind_volume.remove()
        if self.network:
            self.network.remove()

    def get_client(self):
        # Wait until TLS certificate is generated
        timeout = 30
        while ((not os.path.exists(os.path.join(self.cert_dir, 'cert.pem')) or
                not os.path.exists(os.path.join(self.cert_dir, 'key.pem'))) and
               timeout > 0):
            time.sleep(1)
            timeout = timeout - 1

        if timeout == 0:
            logging.error("""The script could not access the TLS certificates which
            has been created by the Docker in Docker instance. Make sure {} is
            a shared location between this script and the Docker host."""
            .format(self.cert_dir))
            return
        # Use TLS to authenticate
        tls_config = docker.tls.TLSConfig(ca_cert=os.path.join(self.cert_dir, 'ca.pem'),
                verify=os.path.join(self.cert_dir, 'ca.pem'),
                client_cert=(os.path.join(self.cert_dir, 'cert.pem'), os.path.join(self.cert_dir, 'key.pem')),
                assert_hostname=False)

        logging.info("Connecting to Docker Daemon at {}".format(self.docker_host))
        dind_client = docker.DockerClient(base_url=self.docker_host, tls=tls_config)
        return dind_client

    def save_tar(self, output_file):
        output_mount_dir = "/mnt"
        logging.info("Storing container bundle to {}".format(self.output_dir_host))

        # Get tar filename and compression command to convert to compressed tar
        # locally in a second command (we do not have the compression utils in
        # the tar container).
        (output_file_tar, compression_command) = self.get_compression_command(output_file)

        # Use a container to tar the Docker storage backend instead of the
        # built-in save_tar() is more flexible...
        tar_container = self.host_client.containers.run("debian:buster",
                volumes = {
                            self.DIND_VOLUME_NAME: {'bind': '/var/lib/docker/', 'mode': 'ro'},
                            self.output_dir_host: {'bind': output_mount_dir, 'mode': 'rw'}
                          },
                command = self.get_tar_command(os.path.join(output_mount_dir, output_file_tar)),
                auto_remove=True)

        output_filepath = os.path.join(self.output_dir, output_file)
        if os.path.exists(output_filepath):
            os.remove(output_filepath)
        subprocess.run(compression_command, cwd=self.output_dir, check=True)

def download_containers_by_compose_file(output_dir, compose_file, host_workdir,
        use_host_docker=False, platform="linux/arm/v7", output_filename="docker-storage.tar"):

    # Open Docker Compose file
    if not os.path.isabs(compose_file):
        base_dir = os.path.dirname(os.path.abspath(compose_file))
    else:
        base_dir = os.path.dirname(compose_file)

    environment = compose.config.environment.Environment.from_env_file(base_dir)
    config = compose.config.find(base_dir, [ os.path.basename(compose_file) ], environment, None)
    cfg = compose.config.load(config)

    logging.info("Starting DIND container")
    if use_host_docker:
        logging.info("Using DockerManager")
        manager = DockerManager(output_dir)
    else:
        logging.info("Using DindManager")
        manager = DindManager(output_dir, host_workdir)

    manager.start("host", default_platform=platform)

    try:
        dind_client = manager.get_client()
        if dind_client is None:
            return

        # Now we can fetch the containers...
        for service in cfg.services:
            image = service['image']
            logging.info("Fetching container image {}".format(image))
            image = dind_client.images.pull(image, platform=platform)

            # Replace image with concrete Image ID
            service['image'] = image.attrs['RepoDigests'][0]

        logging.info("Save Docker Compose file")
        f = open(os.path.join(manager.output_dir, "docker-compose.yml"), "w")
        f.write(compose.config.serialize.serialize_config(cfg))
        f.close()
       
        logging.info("Exporting storage")
        manager.save_tar(output_filename)

    finally:
        logging.info("Stopping DIND container")
        manager.stop()

if __name__== "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--host-docker",
                        help = """Use host Docker instance (instead of
                        Docker-in-Docker). Note that this often is not possible
                        since there are already images in the Docker storage which
                        should not be part of the bundle.""")
    parser.add_argument("--output-directory", dest="output_directory",
                        help="Specify the bundle output directory",
                        default="output")
    parser.add_argument("--host-workdir", dest="host_workdir",
                        help="""Location where Docker needs to bind mount to.
                        This is useful if this script runs in a container
                        and accesses a Docker Engine on the host.
                        """)
    parser.add_argument("-f", "--file", dest="compose_file",
                        help="Specify an alternate compose file",
                        default="docker-compose.yml")
    parser.add_argument("--platform", dest="platform",
                        help="""Specify platform to make sure fetching the correct
                        image when multi-platform images are specified""",
                        default="linux/arm/v7")
    args = parser.parse_args()

    # This is required to share a bind mounted location (for the TLS
    # certificate) between the DIND instace and the accessing client (this
    # script). If that accessing client is by itself inside a container, then
    # the location of host Docker might not match the location this script is
    # running in.
    host_workdir = args.host_workdir
    if host_workdir is None:
        host_workdir = os.getcwd()

    download_containers_by_compose_file(args.output_directory, args.compose_file,
            host_workdir, args.host_docker, args.platform)