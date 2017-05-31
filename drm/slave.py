import json
import urllib
import tempfile
import re
import os
import shutil
import threading
import time
import requests
from requests.compat import urljoin

import drm
from drm.data import HandbrakeConfig, RipConfig, Disc
from drm.handbrake import Handbrake


MIN_DISK_SPACE_LEFT = 15                # in gb
HEARTBEAT_CHECK_PERIOD = 5             # in seconds


def check_master(ip, port):
    url = 'http://{ip}:{port}/version'.format(ip=ip, port=port)
    r = requests.get(url)
    if r.status_code != 200:
        # Can't connect to master
        return False

    version = json.loads(r.text)

    if version != drm.__version__:
        return False

    return True


def get_job(ip, port):
    url = 'http://{ip}:{port}/jobs/'.format(ip=ip, port=port)
    r = requests.get(url)
    if r.status_code != 200:
        # TODO
        raise Exception()

    # parse json
    data = json.loads(r.text)

    job_id = data['name']

    rip_config = RipConfig()
    rip_config.fixes = data['rip_config']['fixes']
    rip_config.len_range = data['rip_config']['len_range']
    rip_config.a_lang = data['rip_config']['a_lang']
    rip_config.s_lang = data['rip_config']['s_lang']

    hb_config = HandbrakeConfig()
    hb_config.preset = data['hb_config']['preset']
    hb_config.quality = data['hb_config']['quality']
    hb_config.h264_preset = data['hb_config']['h264_preset']
    hb_config.h264_profile = data['hb_config']['h264_profile']
    hb_config.h264_level = data['hb_config']['h264_level']
    hb_config.fixes = data['hb_config']['fixes']

    return (job_id, rip_config, hb_config)


def get_input_file(ip, port, job_id, path):
    url = 'http://{ip}:{port}/jobs/{job_id}'.format(ip=ip, port=port, job_id=job_id)
    r = requests.get(url, stream=True)

    filename = re.findall("filename=(.+)", r.headers['content-disposition'])
    if (len(filename) != 1):
        raise Exception()
    filename = filename[0]

    filepath = os.path.join(path, filename)

    if r.status_code == 200:
        with open(filepath, 'wb') as fd:
            for chunk in r.iter_content(1024):
                fd.write(chunk)

    return filename


def send_files(ip, port, job_id, files, temp_dir):
    print('send_files')

    # currently this function always ends the job
    status = {'state': 'DONE'}

    file_dict = {}
    for f in files:
        file_dict[os.path.basename(f)] = open(os.path.join(temp_dir, f), 'rb')

    url = 'http://{ip}:{port}/jobs/{job_id}'.format(ip=ip, port=port, job_id=job_id)
    r = requests.post(url, files=file_dict, data=status)


class HeartbeatContextManager(object):
    def __init__(self, ip, port, job_id):
        self.ip = ip
        self.port = port
        self.job_id = job_id

    def do_hearbeat(self):
        status = {'state': 'WORKING'}
        url = 'http://{ip}:{port}/jobs/{job_id}'.format(ip=self.ip, port=self.port, job_id=self.job_id)
        r = requests.post(url, files={}, data=status)

    def heartbeat_thread(self):
        while True:
            time.sleep(HEARTBEAT_CHECK_PERIOD)
            self.do_hearbeat()

    def __enter__(self):
        self.t = threading.Thread(target=self.heartbeat_thread)
        self.t.start()

    def __exit__(self, *exc):
        self.t.join()


def slave_start(ip, port):
    if not check_master(ip, port):
        print('drm version on master/slave do not match')
        return

    while True:
        temp_dir = tempfile.TemporaryDirectory()

        # Check if there is still some disk space left
        (_, _, free_mem) = shutil.disk_usage(temp_dir.name)
        free_mem_gb = free_mem / 1024 / 1024 / 1024
        if free_mem_gb < MIN_DISK_SPACE_LEFT:
            print('Warning: Free space in temp dir might not be enough')

        try:
            (job_id, rip_config, hb_config) = get_job(ip, port)
        except Exception:
            break

        with HeartbeatContextManager(ip, port, job_id):
            input_file_name = get_input_file(ip, port, job_id, temp_dir.name)

            in_path = os.path.join(temp_dir.name, input_file_name)

            hb = Handbrake()
            titles = hb.scan_disc(in_path, 'use_libdvdread' in rip_config.fixes)
            titles = hb.filter_titles(titles,
                                      rip_config.len_range[0], rip_config.len_range[1],
                                      rip_config.a_lang, rip_config.s_lang)

            if 'remove_duplicate_tracks' in rip_config.fixes:
                titles = hb.remove_duplicate_tracks(titles)

            out_list = hb.encode_titles(hb_config, rip_config, titles, in_path, temp_dir.name)

            send_files(ip, port, job_id, out_list, temp_dir.name)

        print('job done')
