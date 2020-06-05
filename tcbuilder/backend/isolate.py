import datetime
import os
import sys
import subprocess
import paramiko
from subprocess import Popen
from subprocess import PIPE
from tcbuilder.backend.common import TorizonCoreBuilderError

ignore_files = ['gshadow', 'machine-id', 'group', 'shadow', 'systemd/system/sysinit.target.wants/run-postinsts.service',
                'ostree/remotes.d/toradex-nightly.conf', 'docker/key.json', '.updated', '.pwd.lock', 'group-',
                'gshadow-', 'hostname', 'ssh/ssh_host_rsa_key', 'ssh/ssh_host_rsa_key.pub', 'ssh/ssh_host_ecdsa_key',
                'ssh/ssh_host_ecdsa_key.pub',
                'ssh/ssh_host_ed25519_key',
                'ssh/ssh_host_ed25519_key.pub']
TAR_NAME = 'isolated_changes.tar'


def run_command_with_sudo(client, command, password):
    stdin, stdout, stderr = client.exec_command(command=command, get_pty=True)
    stdin.write(password + '\n')
    stdin.flush()
    status = stdout.channel.recv_exit_status()  # wait for exec_command to finish

    return status, stdin, stdout


def run_command_without_sudo(client, command):
    stdin, stdout, stderr = client.exec_command(command)
    status = stdout.channel.recv_exit_status()  # wait for exec_command to finish

    return status, stdin, stdout


def ignore_changes_deletion(change):
    if change.split()[1] in ignore_files:
        return False  # ignore file

    return True


def remove_tmp_dir(client, tmp_dir_name):
    run_command_without_sudo(client, 'rm -rf ' + tmp_dir_name)


def check_path(p):
    return '/' if p.rsplit('/', 1)[0] == p else '/{}/'.format(
        p.rsplit('/', 1)[0])


def whiteouts(client, sftp_channel, tmp_dir_name, deleted_f_d):
    try:
        # check if deleted file/dir was in subdirectory of /etc --> '/' for file/dir at /etc
        path = check_path(deleted_f_d)
        if path != '/':  # file/dir was in subdirectory of of /etc
            # check if any file exists other than file/dir deleted in same subdirectory of /etc
            d_list = sftp_channel.listdir('/etc' + path)
            if not d_list:  # entire content(s) deleted
                deleted_file_dir_to_tar = 'etc' + path + '.wh..wh..opq'
            else:
                deleted_file_dir_to_tar = 'etc' + path + '.wh.' \
                                          + deleted_f_d.rsplit('/', 1)[1]
        else:
            deleted_file_dir_to_tar = 'etc' + path + '.wh.' \
                                      + deleted_f_d

        # create deleted files/dir in torizonbuilder tmp directory with whiteout format
        create_deleted_info_cmd = 'mkdir -p {0}/{1} && touch {0}/{2}'.format(tmp_dir_name,
                                                                             deleted_file_dir_to_tar.rsplit(
                                                                                 '/', 1)[0],
                                                                             deleted_file_dir_to_tar)
        status, stdin, stdout = run_command_without_sudo(client, create_deleted_info_cmd)
        if status > 0:
            raise TorizonCoreBuilderError('Deleted Files information is not moved to host' + stdout.read().decode(
                'utf-8').strip())
    except:
        # need to be handled by frontend
        raise


def isolate_user_changes(rcv_args):
    diff_dir = os.path.abspath(rcv_args.diff_dir)
    r_name_ip = rcv_args.remoteip
    r_username = rcv_args.remote_username
    r_password = rcv_args.remote_password

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        client.connect(hostname=r_name_ip,
                       username=r_username,
                       password=r_password)
        # get config diff
        status, stdin, stdout = run_command_with_sudo(client, 'sudo ostree admin config-diff', r_password)
        if status > 0:
            client.close()
            raise TorizonCoreBuilderError('Unable to get config diff' + stdout.read().decode('utf-8').strip())

        output = stdout.read().decode("utf-8").strip().split("\r\n")
        output = output[2:]  # remove password keyword and password entered from output
        # filter out files
        changed_itr = filter(ignore_changes_deletion, output)
        changes = list(changed_itr)
        if not changes:
            raise TorizonCoreBuilderError('no change is made in /etc by user')

        sftp = client.open_sftp()
        if sftp is not None:
            # perform all operations in /tmp
            tmp_dir_name = '/tmp/torizon-builder-' + str(datetime.datetime.now().date()) + '_' + str(
                datetime.datetime.now().time()).replace(':', '-')
            sftp.mkdir(tmp_dir_name)

            files_dir_to_tar = ''
            f_delete_exists = False
            # append /etc because ostree config provides file/dir names relative to /etc
            for item in changes:
                if item.split()[0] != 'D':
                    files_dir_to_tar += '/etc/' + item.split()[1] + ' '
                else:
                    f_delete_exists = True
                    whiteouts(client, sftp, tmp_dir_name, item.split()[1])

            if f_delete_exists:
                tar_command = "sudo tar --exclude={0} --xattrs --acls -cf {1}/{0} -C {1} . {2}". \
                    format(TAR_NAME, tmp_dir_name, files_dir_to_tar)
            else:  # don't include current directory i.e. '.' --> whiteout files does not exist in /tmp/toriozn-builder/
                tar_command = "sudo tar --xattrs --acls -cf {1}/{0} {2}".format(TAR_NAME,
                                                                                tmp_dir_name,
                                                                                files_dir_to_tar)
            # make tar
            status, stdin, stdout = run_command_with_sudo(client, tar_command, r_password)
            if status > 0:
                remove_tmp_dir(client, tmp_dir_name)
                sftp.close()
                client.close()
                raise TorizonCoreBuilderError('Unable to collect info' + stdout.read().decode('utf-8').strip())

            # get the tar
            sftp.get(tmp_dir_name + '/' + TAR_NAME, diff_dir
                     + '/' + TAR_NAME, None)
            remove_tmp_dir(client, tmp_dir_name)
            sftp.close()
        else:
            client.close()
            raise TorizonCoreBuilderError('Unable to connect to the host')

        client.close()

        # extract tar
        extract_tar_cmd = "tar --acls --xattrs --overwrite --preserve-permissions " \
                          "-xf {0}/{1} -C {0}/".format(
            diff_dir, TAR_NAME)
        subprocess.check_output(extract_tar_cmd, shell=True, stderr=subprocess.STDOUT)
        subprocess.check_output('rm {}/{}'.format(diff_dir,
                                                  TAR_NAME), shell=True, stderr=subprocess.STDOUT)
    except:
        raise