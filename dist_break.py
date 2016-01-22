#!/usr/bin/env python3

from celery import Celery
from celery.result import AsyncResult
from celery.task.control import discard_all
import argparse
import os
import sys
import subprocess
import signal
from threading import Thread
import locale
import codecs
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer, ThreadedFTPServer
from ftplib import FTP
import tempfile
import time
import uuid
import hashlib
import shutil
import datetime
import logging
import json


# TODO: support subdirs
# TODO: detect new files during runtime
# TODO: maybe move directories to cfg file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('dist_hb')

FTP_SERVER_PORT = 50000
HANDBRAKE_CLI_BIN = 'HandBrakeCLI'

app = Celery('tasks', backend='rpc://')


class Track(object):
    def __init__(self, index, lang):
        self.index = index
        self.lang  = lang

    def __str__(self):
        return self.lang

    def __repr__(self):
        return self.__str__()

class Title(object):
    def __init__(self, index):
        self.index    = index
        self.duration = ""
        self.a_tracks = []
        self.s_tracks = []

    def __str__(self):
        ret = "Title: {num} - {duration} - A: {a_tracks} S: {s_tracks}"
        return ret.format(num=self.index, duration=self.duration, a_tracks=self.a_tracks, s_tracks=self.s_tracks)

class Disc(object):
    def __init__(self, path):
        self.titles  = []
        self.path    = path
        self.scanned = False

    def __str__(self):
        ret = self.path + ' (' + ''.join([str(t) for t in self.titles]) + ')'
        return ret

    def __repr__(self):
        return self.__str__()

class HandbrakeConfig(object):
    def __init__(self, preset=None, quality=20, h264_preset='medium', h264_profile='high', h264_level='4.1'):
        if h264_preset not in ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow', 'placebo']:
            raise Exception('Preset invalid')
        if h264_profile not in ['baseline', 'main', 'high', 'high10', 'high422', 'high444']:
            raise Exception('Profile invalid')
        if h264_level not in ['4.1']:   # TODO
            raise Exception('Level invalid')
        self.preset = preset
        self.quality = quality
        self.h264_preset = h264_preset
        self.h264_profile = h264_profile
        self.h264_level = h264_level

class RipConfig(object):
    def __init__(self, a_lang=['eng', 'deu'], s_lang=['eng', 'deu'], len_range=(15, 50)):
        self.a_lang = a_lang
        self.s_lang = s_lang
        self.len_range = len_range

class Job(object):
    NOT_STARTED = 0
    RUNNING     = 1
    DONE        = 2
    FAILED      = 3

    def __init__(self, disc, ftp, rip_config, hb_config, args):
        if not isinstance(disc, Disc):
            raise ValueError()
        if not isinstance(rip_config, RipConfig):
            raise ValueError()
        if not isinstance(hb_config, HandbrakeConfig):
            raise ValueError()
        self.disc = disc
        self.hash = self._calc_hash(os.path.join(args.indir, self.disc.path))

        self.rip_config = rip_config
        self.hb_config = hb_config
        self.args = args
        self.name = str(uuid.uuid4())
        self.state = Job.NOT_STARTED
        self.job_result = None

        self.setup_env(ftp)

    def __str__(self):
        return self.name + " - " + self.disc.path

    def _calc_hash(self, filepath):
        hash = hashlib.md5()
        with open(filepath, 'rb') as fd:
            for chunk in iter(lambda: fd.read(4096), b""):
                hash.update(chunk)
        return hash.hexdigest()

    def check_hash(self, filepath):
        return self.hash == self._calc_hash(filepath)

    def setup_env(self, ftp):
        self.state = Job.RUNNING
        temp_path = os.path.join(self.args.tempdir, self.name)
        os.mkdir(temp_path)
        ftp.add_user(self.name, self.args.indir, temp_path)

    def teardown_env(self, ftp):
        if isinstance(self.job_result, AsyncResult):
            self.job_result = self.job_result.get()

        job_path = os.path.join(self.args.tempdir, self.name)
        out_path = self.args.out
        files_valid = True
        for f in self.job_result:
            f_path = os.path.join(job_path, f['name'])
            f_hash = self._calc_hash(f_path)
            if f_hash != f['hash']:
                files_valid = False

        if files_valid:
            for f in self.job_result:
                f_path = os.path.join(job_path, f['name'])
                try:
                    shutil.move(f_path, out_path)
                except shutil.Error:
                    print('Output file {filename} already exists. Skipping file...'.format(filename=f_path))
                    # TODO: what to do, if file already exists
            self.state = Job.DONE
        else:
            self.state = Job.FAILED

        shutil.rmtree(job_path)
        ftp.rem_user(self.name)

    def run(self, job_runner):
        self.job_result = job_runner(self, self.args.ip, FTP_SERVER_PORT)

    def join(self):
        if isinstance(self.job_result, AsyncResult):
            self.job_result = self.job_result.get()


class Handbrake(object):
    @staticmethod
    def scan_disc(disc_path):
        # TODO: detect if disc_path does not exist
        # TODO: accept disc as argument

        logger.info('Scanning %s...' % (disc_path))
        cmd = [HANDBRAKE_CLI_BIN, '-i', disc_path, '-t', '0']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        stderr = codecs.decode(stderr, 'utf-8', 'replace')
        titles = Handbrake._parse_scan(stderr)
        return titles

    @staticmethod
    def _parse_scan(scan_output):
        scan_output = scan_output.split('\n')
        temp = []
        for line in scan_output:
            if '+ ' in line:
                temp.append(line)

        in_s_tracks = False
        in_a_tracks = False
        title_temp = None
        title_list = []
        for line in temp:
            if (in_a_tracks or in_s_tracks) and (line[:4] == '  + '):
                in_s_tracks = False
                in_a_tracks = False

            if '  + audio tracks:' in line:
                in_a_tracks = True
                continue
            elif '  + subtitle tracks:' in line:
                in_s_tracks = True
                continue
            elif "  + duration:" in line:
                temp = line[14:].split(':')
                title_temp.duration = datetime.time(hour=int(temp[0]), minute=int(temp[1]), second=int(temp[2]))
                continue
            elif '+ title ' in line:
                title_temp = Title(int(line[8:-1]))
                title_list.append(title_temp)
                in_s_tracks = False
                in_a_tracks = False
                continue
            elif in_a_tracks:
                begin = line.find('iso639-2: ')
                if begin != -1:
                    begin += len('iso639-2: ')
                    end = line.find(')', begin)
                    lang = line[begin:end]
                    temp1 = line.find('+ ') + len('+ ')
                    temp2 = line.find(', ', temp1)
                    idx = line[temp1:temp2]
                    title_temp.a_tracks.append(Track(int(idx), str(lang)))
            elif in_s_tracks:
                begin = line.find('iso639-2: ')
                if begin != -1:
                    begin += len('iso639-2: ')
                    end = line.find(')', begin)
                    lang = line[begin:end]
                    temp1 = line.find('+ ') + len('+ ')
                    temp2 = line.find(', ', temp1)
                    idx = line[temp1:temp2]
                    title_temp.s_tracks.append(Track(int(idx), str(lang)))
        return title_list

    @staticmethod
    def filter_titles(title_list, min_time, max_time, a_lang_list, s_lang_list):
        iso639_alt_lut = {
            "alb": "sqi", "arm": "hye", "baq": "eus", "bod": "tib", "bur": "mya",
            "ces": "cze", "chi": "zho", "cym": "wel", "deu": "ger", "dut": "nld",
            "fas": "per", "fra": "fre", "geo": "kat", "gre": "ell", "ice": "isl",
            "mac": "mkd", "mao": "mri", "may": "msa", "ron": "rum", "slk": "slo"
        }
        iso639_alt_lut.update({v: k for k, v in iso639_alt_lut.items()})

        min_time = datetime.time(hour=0, minute=min_time, second=0)
        max_time = datetime.time(hour=0, minute=max_time, second=0)

        a_lang_list = a_lang_list + [iso639_alt_lut[e] for e in a_lang_list if e in iso639_alt_lut]
        s_lang_list = s_lang_list + [iso639_alt_lut[e] for e in s_lang_list if e in iso639_alt_lut]

        ret = []
        for t in title_list:
            if min_time < t.duration < max_time:
                t.a_tracks = [a for a in t.a_tracks if a.lang in a_lang_list]
                t.s_tracks = [s for s in t.s_tracks if s.lang in s_lang_list]
                ret.append(t)
        return ret

    @classmethod
    def build_cmd_line(cls, input, output, title, a_tracks, s_tracks, preset=None,
                       quality=20, h264_preset='medium', h264_profile='high', h264_level='4.1'):
        if h264_preset not in ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow', 'placebo']:
            raise Exception('Preset invalid')
        if h264_profile not in ['baseline', 'main', 'high', 'high10', 'high422', 'high444']:
            raise Exception('Profile invalid')
        if h264_level not in ['4.1']:   # TODO
            raise Exception('Level invalid')

        cmd = ['HandBrakeCLI']
        cmd.extend(['-i', input])
        cmd.extend(['-o', output])
        cmd.extend(['-t', str(title)])
        cmd.extend(['-a', Handbrake._tracks_to_csl(a_tracks)])
        cmd.extend(['-s', Handbrake._tracks_to_csl(s_tracks)])
        if preset is not None:
            cmd.extend(['-Z', preset])
        cmd.extend(['-f', 'mkv'])
        cmd.extend(['-m'])
        cmd.extend(['-e', 'x264'])
        cmd.extend(['-q', str(quality)])
        cmd.extend(['-E', 'copy'])
        cmd.extend(['--loose-anamorphic'])
        cmd.extend(['--decomb'])
        cmd.extend(['--x264-preset', h264_preset])
        cmd.extend(['--x264-profile', h264_profile])
        cmd.extend(['--h264-level', h264_level])
        return cmd


    @staticmethod
    def encode_titles(hb_config, title_list, in_path, out_path):
        logging.info('encoding titles...')

        ret = []
        for t in title_list:
            logging.info('encoding title {}'.format(t.index))
            title_path = os.path.basename(in_path) + '.' + str(t.index) + '.mkv'
            title_out_path = os.path.join(out_path, title_path)
            # TODO: DEBUG - Optionen anpassen (und aus config holen?)
            cmd = Handbrake.build_cmd_line(in_path, title_out_path, t.index, t.a_tracks, t.s_tracks,
                                           quality=hb_config.quality, h264_preset=hb_config.h264_preset,
                                           h264_profile=hb_config.h264_profile, h264_level=hb_config.h264_level)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
            stdout = codecs.decode(stdout, 'utf-8', 'replace')
            stderr = codecs.decode(stderr, 'utf-8', 'replace')

            ret.append(title_path)
        return ret

    @classmethod
    def _tracks_to_csl(cls, track_list):
        temp = ""
        for i in range(len(track_list)):
            temp += str(track_list[i].index)
            if i != len(track_list) - 1:
                temp += ','
        return temp

class FTPServerWrapper(object):
    class TestHandler(FTPHandler):
        def on_incomplete_file_received(self, file):
            pass
            print('on_incomplete_file_received({})'.format(file))
            # TODO: delete incomplete file, mark job as unfinished

    class FTPServerRunner(Thread):
        def __init__(self, server):
            self.server = server
            super(FTPServerWrapper.FTPServerRunner, self).__init__()

        def run(self):
            self.server.serve_forever()

    def __init__(self, port=('', FTP_SERVER_PORT)):
        self.auth = DummyAuthorizer()
        self.handler = FTPServerWrapper.TestHandler
        self.handler.authorizer = self.auth
        self.server = ThreadedFTPServer(port, self.handler)

        self.users = []
        self.t = FTPServerWrapper.FTPServerRunner(self.server)
        self.t.start()

    def __del__(self):
        self.server.close_all()
        self.server.close()
        del self.server

    def add_user(self, name, r_dir, w_dir):
        logging.info('adding ftp user {}'.format(name))
        self.users.append(name)
        self.auth.add_user('r-' + str(name), name, r_dir, perm='rl')
        self.auth.add_user('w-' + str(name), name, w_dir, perm='wl')

    def rem_user(self, name):
        logging.info('removing ftp user {}'.format(name))
        try:
            self.users.remove(name)
            self.auth.remove_user('r-' + str(name))
            self.auth.remove_user('w-' + str(name))
        except ValueError:
            pass


class FTPClient(object):
    def __init__(self, host, port, name, r_w):
        self.ftp = FTP()
        self.ftp.connect(host=host, port=port)
        if r_w:
            self.ftp.login(user='r-' + name, passwd=name)
        else:
            self.ftp.login(user='w-' + name, passwd=name)

    def get_file(self, source, dest):
        logging.info('copying {} to {}'.format(source, dest))
        with open(dest, 'wb') as fd:
            def callback(data):
                fd.write(data)
            self.ftp.retrbinary('RETR {ftp_file}'.format(ftp_file=source), callback)

    def put_file(self, source, dest):
        logging.info('copying {} to {}'.format(source, dest))
        print(source, dest)
        with open(source, 'rb') as fd:
            self.ftp.storbinary('STOR {ftp_file}'.format(ftp_file=dest), fd)


############### slave
@app.task
def handbrake_task(job, server_ip, server_port):
    # TODO: check env

    temp_dir = tempfile.TemporaryDirectory()
    in_path = os.path.join(temp_dir.name, job.disc.path)

    # get iso from master
    logger.info('Fetching file from server...')
    ftp_r = FTPClient(server_ip, server_port, job.name, True)
    ftp_r.get_file(job.disc.path, in_path)
    if not job.check_hash(in_path):
        raise Exception()
    del ftp_r

    files = []
    hb = Handbrake()
    titles = hb.scan_disc(in_path)
    titles = hb.filter_titles(titles,
                job.rip_config.len_range[0], job.rip_config.len_range[1],
                job.rip_config.a_lang, job.rip_config.s_lang)
    out_list = hb.encode_titles(job.hb_config, titles, in_path, temp_dir.name)
    for f in out_list:
        files.append({'name': f, 'hash': job._calc_hash(os.path.join(temp_dir.name, f))})

    # send files to master
    ftp_w = FTPClient(server_ip, server_port, job.name, False)
    for f in files:
        ftp_w.put_file(os.path.join(temp_dir.name, f['name']), f['name'])
    del ftp_w

    return files


############## master
def master(args):
    # discard possible jobs from before
    try:
        discard_all()
    except OSError:
        print('Could not connect to host')
        sys.exit(-1)

    ftp = FTPServerWrapper()

    disc_list = []
    for root, dirs, files in os.walk(args.indir):
        if dirs:
            print('Subdirs currently not supported!')
            break
        for f in files:
            disc_list.append(Disc(f))

    job_list = []
    for d in disc_list:
        logger.info('creating job {}'.format(d))
        job = Job(d, ftp, args.rip_config, args.hb_config, args)
        try:
            job.run(handbrake_task.delay)
            job_list.append(job)
        except ConnectionResetError:
            print('Could not run job. Maybe broker credentials invalid?!')

    for job in job_list:
        logger.info('waiting on job {}'.format(job))
        job.join()
        job.teardown_env(ftp)

        if job.state == Job.DONE:
            print('Job done...')
            shutil.move(os.path.join(args.indir, job.disc.path), args.out)
        else:
            print('Job failed...')


############## main
def slave():
    # NOTE: Only one thread at a time, since HB uses multiple processors
    app.worker_main(['worker', '--loglevel=INFO', '-c 1'])


def parse_cfg(cfg_path):
    hb_config = None
    rip_config = None
    broker = None
    try:
        with open(cfg_path, 'r') as fd:
            temp = json.load(fd)

        hb_config = HandbrakeConfig(quality      = temp['hb_config']['quality'],
                                    h264_preset  = temp['hb_config']['h264_preset'],
                                    h264_profile = temp['hb_config']['h264_profile'],
                                    h264_level   = temp['hb_config']['h264_level'])
        rip_config = RipConfig(a_lang = temp['rip_config']['a_tracks'],
                               s_lang = temp['rip_config']['s_tracks'],
                               len_range = (temp['rip_config']['min_dur'], temp['rip_config']['max_dur']))
        broker = (temp['broker'].get('ip'), temp['broker'].get('port'), temp['broker'].get('username'), temp['broker'].get('password'))
    except FileNotFoundError:
        logger.warning('Could not open config, using defaults')
    except ValueError:
        logger.warning('Config invalid, using defaults')
    except KeyError:
        logger.warning('Config invalid, using defaults')

    if hb_config is None or rip_config is None or broker is None:
        hb_config = HandbrakeConfig()
        rip_config = RipConfig()
        broker = (None, None, None, None)

    return hb_config, rip_config, broker


def build_broker_url(user, password, ip, port):
    broker_url  = 'amqp://'
    broker_url += str(user) if user is not None else ''
    broker_url += (':' + str(password)) if password is not None else ''
    broker_url += '@' if user is not None else ''
    broker_url += str(ip) if ip is not None else ''
    broker_url += (':' + str(port)) if port is not None else ''
    return broker_url


def dist_break():
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--master', dest='master',  action='store_true')
    parser.add_argument('--slave',  dest='slave',   action='store_true')
    parser.add_argument('--in',     dest='indir',   action='store',      default='in/')
    parser.add_argument('--out',    dest='out',     action='store',      default='out/')
    parser.add_argument('--temp',   dest='tempdir', action='store',      default=None)
    parser.add_argument('--cfg',    dest='config',  action='store',      default='dist_break.cfg')
    args = parser.parse_args()

    (args.hb_config, args.rip_config, args.broker) = parse_cfg(args.config)

    broker_url = build_broker_url(args.broker[2], args.broker[3], args.broker[0], args.broker[1])

    app.conf.update(BROKER_URL = broker_url)

    if args.tempdir is None:
        tempdir = tempfile.TemporaryDirectory()
        args.tempdir = tempdir.name

    if args.master == args.slave:
        sys.exit('please select either master or slave!')

    if args.slave:
        print('Starting as slave...')
        slave()
    if args.master:
        print('Starting as master...')
        master(args)


if __name__ == '__main__':
    dist_break()
