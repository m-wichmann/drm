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
import json

from dist_brake.data import HandbrakeConfig, RipConfig, Disc
from dist_brake.job import Job
from dist_brake.task import start_worker, handbrake_task
from dist_brake.handbrake import Handbrake


import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('dist_hb')


# TODO: support subdirs
# TODO: detect new files during runtime
# TODO: maybe move directories to cfg file




def master(hb_config, rip_config, in_path, out_path):
    # discard possible jobs from before
    try:
        discard_all()
    except OSError:
        print('Could not connect to host')
        sys.exit(-1)

    disc_list = []
    for root, dirs, files in os.walk(in_path):
        if dirs:
            print('Subdirs currently not supported!')
            break
        for f in files:
            disc_list.append(Disc(os.path.join(root, f), f))

    job_list = []
    for d in disc_list:
        logger.info('creating job {}'.format(d))
        job = Job(d, rip_config, hb_config, in_path, out_path)
        try:
            job.run(handbrake_task.delay)
            job_list.append(job)
        except ConnectionResetError:
            print('Could not run job. Maybe broker credentials invalid?!')

    for job in job_list:
        logger.info('waiting on job {}'.format(job))
        job.join()
        job.teardown_env()

        if job.state == Job.DONE:
            print('Job done...')
            shutil.move(job.disc.local_path, out_path)
        else:
            print('Job failed...')


def parse_cfg_master(cfg_path):
    with open(cfg_path, 'r') as fd:
        try:
            data = json.load(fd)
            hb_config = HandbrakeConfig(quality      = data['hb_config']['quality'],
                                        h264_preset  = data['hb_config']['h264_preset'],
                                        h264_profile = data['hb_config']['h264_profile'],
                                        h264_level   = data['hb_config']['h264_level'])
            rip_config = RipConfig(a_lang = data['rip_config']['a_tracks'],
                                   s_lang = data['rip_config']['s_tracks'],
                                   len_range = (data['rip_config']['min_dur'],
                                                data['rip_config']['max_dur']),
                                   fixes = data['rip_config']['fixes'])
            in_path = data['in_path']
            out_path = data['out_path']
        except KeyError:
            sys.exit('master config not valid')

    return (hb_config, rip_config, in_path, out_path)


def parse_cfg_slave(cfg_path):
    with open(cfg_path, 'r') as fd:
        try:
            data = json.load(fd)
            ip = data['ip']
            user = data['user']
            password = data['password']
        except KeyError:
            sys.exit('slave config not valid')

    return (ip, user, password)





def rip(out_dir):
    while (1):
        name = input('Please enter disc name: ')

        if name == '':
            sys.exit(0)

        name = name.upper()

        temp_dir = tempfile.TemporaryDirectory()
        out_path = os.path.join(out_dir, name + '.iso')

        cmd = ['dvdbackup', '-M', '-i', '/dev/dvd', '-o', temp_dir.name, '-n', name]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()

        cmd = ['genisoimage', '-dvd-video', '-o', out_path, os.path.join(temp_dir.name, name)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()

        print('Done {}!'.format(name))
        os.system('eject')




def list_titles(target_dir):
    for root, dirs, files in os.walk(target_dir):
        for f in files:
            print(os.path.join(root, f), end='')
            l = Handbrake.scan_disc(os.path.join(root, f))
            l = Handbrake.filter_titles(l, 15, 250, ['deu', 'eng', 'spa', 'jpa'], ['deu', 'eng', 'spa', 'jpa'])

            print(" =>", len(l))

            if (len(l) == 0):
                print("  ==> Error")


def dist_brake():
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--master', dest='master',  action='store', default=None)
    parser.add_argument('--slave',  dest='slave',   action='store', default=None)
    parser.add_argument('--rip',    dest='rip',     action='store_true', default=None)
    parser.add_argument('--list',   dest='list',    action='store_true', default=None)
    parser.add_argument('--dir',    dest='dir',     action='store', default=None)
    args = parser.parse_args()

    if args.rip:
        if args.dir is None:
            sys.exit('please provide --dir')
        rip(args.dir)
        sys.exit(0)

    if args.list:
        if args.dir is None:
            sys.exit('please provide --dir')
        list_titles(args.dir)
        sys.exit(0)

    if bool(args.master) == bool(args.slave):
        sys.exit('please select either master, slave, rip or list!')

    if args.master is not None:
        (hb_config, rip_config, in_path, out_path) = parse_cfg_master(args.master)
    elif args.slave is not None:
        (ip, user, password) = parse_cfg_slave(args.slave)

    if args.slave:
        print('Starting as slave...')
        start_worker(ip, user, password)
    elif args.master:
        print('Starting as master...')
        master(hb_config, rip_config, in_path, out_path)


if __name__ == '__main__':
    dist_brake()
