import os
import hashlib
import uuid
import tempfile
import shutil
from drm.data import HandbrakeConfig, RipConfig, Disc

import logging
logger = logging.getLogger('drm')


temp_dir = tempfile.TemporaryDirectory()


class Job(object):
    NOT_STARTED = 0
    RUNNING = 1
    DONE = 2
    FAILED = 3

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

        self.name = str(uuid.uuid4())
        self.temp_path = os.path.join(temp_dir.name, self.name)
        print('temp_path: ', self.temp_path)
        self.state = Job.NOT_STARTED
        self.job_result = None

        self.files = []

        self.setup_env()

    def __str__(self):
        return self.name + " - " + self.disc.local_path

    def repr_json(self):
        return dict(disc=self.disc, rip_config=self.rip_config, hb_config=self.hb_config, out_path=self.out_path, in_path=self.in_path, name=self.name, temp_path=self.temp_path, state=self.state, job_result=self.job_result)

    def setup_env(self):
        self.state = Job.RUNNING
        os.mkdir(self.temp_path)

    def teardown_env(self):
        print('teardown_env')

        # TODO: this is wrong!
        if self.job_result is None:
            self.job_result = {}

        for f in self.files:
            try:
                shutil.move(f, self.out_path)
            except shutil.Error:
                print('Output file {filename} already exists. Skipping file...'.format(filename=f))
                # TODO: what to do, if file already exists
        self.state = Job.DONE

        shutil.rmtree(self.temp_path)
