import os
import hashlib
import uuid
import tempfile
import shutil
from celery.result import AsyncResult
from dist_brake.data import HandbrakeConfig, RipConfig, Disc
from dist_brake.ftp import ftp_get_server

import logging
logger = logging.getLogger('dist_hb')


temp_dir = tempfile.TemporaryDirectory()


class Job(object):
    NOT_STARTED = 0
    RUNNING     = 1
    DONE        = 2
    FAILED      = 3

    def __init__(self, disc, rip_config, hb_config, in_path, out_path):
        if not isinstance(disc, Disc):
            raise ValueError()
        if not isinstance(rip_config, RipConfig):
            raise ValueError()
        if not isinstance(hb_config, HandbrakeConfig):
            raise ValueError()

        self.disc = disc
        self.rip_config = rip_config
        self.hb_config = hb_config
        self.out_path = out_path
        self.in_path = in_path

        self.hash = self._calc_hash(self.disc.local_path)
        self.name = str(uuid.uuid4())
        self.temp_path = os.path.join(temp_dir.name, self.name)
        self.state = Job.NOT_STARTED
        self.job_result = None

        self.setup_env()

    def __str__(self):
        return self.name + " - " + self.disc.local_path

    def _calc_hash(self, filepath):
        hash = hashlib.md5()
        with open(filepath, 'rb') as fd:
            for chunk in iter(lambda: fd.read(4096), b""):
                hash.update(chunk)
        return hash.hexdigest()

    def check_hash(self, filepath):
        return self.hash == self._calc_hash(filepath)

    def setup_env(self):
        self.state = Job.RUNNING
        os.mkdir(self.temp_path)
        ftp_get_server().add_user(self.name, self.in_path, self.temp_path)

    def teardown_env(self):
        if isinstance(self.job_result, AsyncResult):
            self.job_result = self.job_result.get()

        if self.job_result is None:
            self.job_result = {}

        files_valid = True
        for f in self.job_result:
            f_path = os.path.join(self.temp_path, f['name'])
            f_hash = self._calc_hash(f_path)
            if f_hash != f['hash']:
                files_valid = False

        if files_valid:
            for f in self.job_result:
                f_path = os.path.join(self.temp_path, f['name'])
                try:
                    shutil.move(f_path, self.out_path)
                except shutil.Error:
                    print('Output file {filename} already exists. Skipping file...'.format(filename=f_path))
                    # TODO: what to do, if file already exists
            self.state = Job.DONE
        else:
            self.state = Job.FAILED

        shutil.rmtree(self.temp_path)
        ftp_get_server().rem_user(self.name)

    def run(self, job_runner):
        self.job_result = job_runner(self)

    def is_ready(self):
        if isinstance(self.job_result, AsyncResult):
            return self.job_result.ready()
        else:
            return True
