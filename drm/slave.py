import json
import tempfile
import os
import shutil
import threading
import time
import requests
from requests_toolbelt import MultipartEncoder
import logging
import cgi

import drm
from drm.data import HandbrakeConfig, RipConfig, Fix
import drm.handbrake as handbrake


logger = logging.getLogger('drm')


MIN_DISK_SPACE_LEFT = 15                # in gb
HEARTBEAT_CHECK_PERIOD = 5             # in seconds


class JobFailedError(Exception):
    pass


class AllJobsDoneError(Exception):
    pass


class ServerNotAvailableError(Exception):
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
        raise ServerNotAvailableError('Request failed') from e

    if r.status_code != 200:
        raise ServerNotAvailableError('Request failed ({})'.format(r.status_code))

    # parse json
    data = json.loads(r.text)

    if data is None:
        raise AllJobsDoneError('No more jobs available')

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
        raise JobFailedError('Could not fetch input file') from e

    try:
        value, params = cgi.parse_header(r.headers['content-disposition'])
        filename = params['filename']
    except KeyError as e:
        raise JobFailedError('Could not fetch input file') from e

    exp_file_size = int(r.headers['content-length'])
    logger.info('Fetching job %s (%.1f GiB)', job_id, exp_file_size / 1024 / 1024 / 1024)

    filepath = os.path.join(path, filename)

    if r.status_code == 200:
        with open(filepath, 'wb') as fd:
            for chunk in r.iter_content(1024):
                fd.write(chunk)

    real_file_size = os.stat(filepath).st_size

    if exp_file_size != real_file_size:
        raise JobFailedError('Fetching input file failed')

    return filename


def send_files(ip, port, job_id, files, temp_dir):
    logger.info('Sending %d files to master', len(files))

    url = 'http://{ip}:{port}/jobs/{job_id}'.format(ip=ip, port=port, job_id=job_id)
    fields = {'state': 'DONE'}
    for f in files:
        fields[os.path.basename(f)] = (os.path.basename(f), open(os.path.join(temp_dir, f), 'rb'))

    m = MultipartEncoder(fields=fields)
    try:
        r = requests.post(url, data=m, headers={'Content-Type': m.content_type})
    except requests.exceptions.ConnectionError:
        raise JobFailedError('Could not send files to server')


class HeartbeatContextManager:
    def __init__(self, ip, port, job_id):
        self.ip = ip
        self.port = port
        self.job_id = job_id
        self.keep_running = True
        self.connection_failed = False

    def __do_hearbeat(self):
        status = {'state': 'WORKING'}
        url = 'http://{ip}:{port}/jobs/{job_id}'.format(ip=self.ip, port=self.port, job_id=self.job_id)
        try:
            r = requests.post(url, files={}, data=status)
        except requests.exceptions.ConnectionError:
            self.connection_failed = True

    def __heartbeat_thread(self):
        while self.keep_running:
            time.sleep(HEARTBEAT_CHECK_PERIOD)
            # Only send heartbeat, if it is still requested
            if self.keep_running:
                self.__do_hearbeat()

    def __enter__(self):
        self.t = threading.Thread(target=self.__heartbeat_thread)
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.keep_running = False
        self.t.join()


def slave_encode(ip, port):
    temp_dir = tempfile.TemporaryDirectory()

    # Check if there is still some disk space left
    (_, _, free_mem) = shutil.disk_usage(temp_dir.name)
    free_mem_gb = free_mem / 1024 / 1024 / 1024
    if free_mem_gb < MIN_DISK_SPACE_LEFT:
        logger.warning('Free space in temp dir might not be enough')

    (job_id, rip_config, hb_config, fixes) = get_job(ip, port)

    with HeartbeatContextManager(ip, port, job_id) as hb_ctx:
        if hb_ctx.connection_failed:
            raise JobFailedError('Heartbeat failed')

        input_file_name = get_input_file(ip, port, job_id, temp_dir.name)

        if hb_ctx.connection_failed:
            raise JobFailedError('Heartbeat failed')

        in_path = os.path.join(temp_dir.name, input_file_name)

        titles = handbrake.scan_disc(in_path, 'use_libdvdread' in fixes)
        titles = handbrake.filter_titles(titles,
                                         rip_config.len_range[0], rip_config.len_range[1],
                                         rip_config.a_lang, rip_config.s_lang)

        if 'remove_duplicate_tracks' in fixes:
            titles = handbrake.remove_duplicate_tracks(titles)

        if hb_ctx.connection_failed:
            raise JobFailedError('Heartbeat failed')

        logger.info('Found %d titles to encode', len(titles))

        # TODO: cancel encoding, if heartbeat failed
        out_list = handbrake.encode_titles(hb_config, rip_config, fixes, titles, in_path, temp_dir.name)

        if hb_ctx.connection_failed:
            raise JobFailedError('Heartbeat failed')

        send_files(ip, port, job_id, out_list, temp_dir.name)

    return job_id


def slave_start(ip, port):
    if not check_master(ip, port):
        logger.error('Server not running or drm version on master/slave do not match')
        return

    while True:
        try:
            job_id = slave_encode(ip, port)
            logger.info('Job %s finished', job_id)
        except JobFailedError as e:
            logger.error('Job failed (%s)', e)
        except AllJobsDoneError as e:
            logger.info('All jobs finished')
            break
        except ServerNotAvailableError as e:
            logger.error('Server not available anymore')
            break
        except KeyboardInterrupt:
            break
