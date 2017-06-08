import json
import tempfile
import re
import os
import shutil
import threading
import time
import requests
import logging

import drm
from drm.data import HandbrakeConfig, RipConfig, Fix
import drm.handbrake as handbrake


logger = logging.getLogger('drm')


MIN_DISK_SPACE_LEFT = 15                # in gb
# TODO
HEARTBEAT_CHECK_PERIOD = 5             # in seconds


class JobFetchException(Exception):
    pass


def check_master(ip, port):
    url = 'http://{ip}:{port}/version'.format(ip=ip, port=port)

    try:
        r = requests.get(url)
    except requests.exceptions.ConnectionError:
        return False

    if r.status_code != 200:
        # Can't connect to master
        return False

    version = json.loads(r.text)

    if version != drm.__version__:
        return False

    return True


def get_job(ip, port):
    url = 'http://{ip}:{port}/jobs/'.format(ip=ip, port=port)

    try:
        r = requests.get(url)
    except requests.exceptions.ConnectionError as e:
        raise JobFetchException('Request failed') from e

    if r.status_code != 200:
        raise JobFetchException('Request failed ({})'.format(r.status_code))

    # parse json
    data = json.loads(r.text)

    if data is None:
        raise JobFetchException('No more jobs available')

    job_id = data['name']
    rip_config = RipConfig.parse_data(data['rip_config'])
    hb_config = HandbrakeConfig.parse_data(data['hb_config'])
    fixes = [Fix.parse_data(fix) for fix in data['fixes']]

    return (job_id, rip_config, hb_config, fixes)


def get_input_file(ip, port, job_id, path):
    url = 'http://{ip}:{port}/jobs/{job_id}'.format(ip=ip, port=port, job_id=job_id)

    try:
        r = requests.get(url, stream=True)
    except requests.exceptions.ConnectionError as e:
        raise JobFetchException('Could not fetch input file') from e

    filename = re.findall('filename=(.+)', r.headers['content-disposition'])
    if len(filename) != 1:
        raise JobFetchException('Could not fetch input file')
    filename = filename[0]

    filepath = os.path.join(path, filename)

    if r.status_code == 200:
        with open(filepath, 'wb') as fd:
            for chunk in r.iter_content(1024):
                fd.write(chunk)

    return filename


def send_files(ip, port, job_id, files, temp_dir):
    # currently this function always ends the job
    status = {'state': 'DONE'}

    file_dict = {}
    for f in files:
        file_dict[os.path.basename(f)] = open(os.path.join(temp_dir, f), 'rb')

    url = 'http://{ip}:{port}/jobs/{job_id}'.format(ip=ip, port=port, job_id=job_id)

    try:
        r = requests.post(url, files=file_dict, data=status)
    except requests.exceptions.ConnectionError:
        raise JobFetchException('Could not send files to server')


class HeartbeatContextManager(object):
    def __init__(self, ip, port, job_id):
        self.ip = ip
        self.port = port
        self.job_id = job_id
        self.keep_running = True

    def do_hearbeat(self):
        status = {'state': 'WORKING'}
        url = 'http://{ip}:{port}/jobs/{job_id}'.format(ip=self.ip, port=self.port, job_id=self.job_id)
        try:
            r = requests.post(url, files={}, data=status)
        except requests.exceptions.ConnectionError:
            logger.warning('Heartbeat failed')
            # TODO: cancel current job

    def heartbeat_thread(self):
        while self.keep_running:
            time.sleep(HEARTBEAT_CHECK_PERIOD)
            # Only send heartbeat, if it is still requested
            if self.keep_running:
                self.do_hearbeat()

    def __enter__(self):
        self.t = threading.Thread(target=self.heartbeat_thread)
        self.t.start()

    def __exit__(self, *exc):
        self.keep_running = False
        self.t.join()


def slave_start(ip, port):
    if not check_master(ip, port):
        logger.error('Server not running or drm version on master/slave do not match')
        return

    while True:
        temp_dir = tempfile.TemporaryDirectory()

        # Check if there is still some disk space left
        (_, _, free_mem) = shutil.disk_usage(temp_dir.name)
        free_mem_gb = free_mem / 1024 / 1024 / 1024
        if free_mem_gb < MIN_DISK_SPACE_LEFT:
            logger.warning('Free space in temp dir might not be enough')

        try:
            (job_id, rip_config, hb_config, fixes) = get_job(ip, port)
        except JobFetchException:
            break

        with HeartbeatContextManager(ip, port, job_id):
            try:
                input_file_name = get_input_file(ip, port, job_id, temp_dir.name)
            except JobFetchException:
                logger.error('Could not fetch input file')
                break

            in_path = os.path.join(temp_dir.name, input_file_name)
            titles = handbrake.scan_disc(in_path, 'use_libdvdread' in fixes)
            titles = handbrake.filter_titles(titles,
                                             rip_config.len_range[0], rip_config.len_range[1],
                                             rip_config.a_lang, rip_config.s_lang)

            if 'remove_duplicate_tracks' in fixes:
                titles = handbrake.remove_duplicate_tracks(titles)

            out_list = handbrake.encode_titles(hb_config, rip_config, fixes, titles, in_path, temp_dir.name)

            try:
                send_files(ip, port, job_id, out_list, temp_dir.name)
            except JobFetchException:
                logger.error('Could not send files')
                break

        logger.info('Job done')

    logger.info('All jobs done...')
