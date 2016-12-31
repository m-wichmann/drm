#!/usr/bin/env python3

from celery import Celery
from celery.result import AsyncResult
from celery.task.control import discard_all
from celery.bin.base import Command
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
import threading
import queue

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



def master_teardown_thread(job_queue, hashing_done_event):
    job_list = []
    while ((not hashing_done_event.is_set()) or (len(job_list) != 0) or (not job_queue.empty())):
        try:
            while True:
                job = job_queue.get(block=False)
                try:
                    job.run(handbrake_task.delay)
                    job_list.append(job)
                except ConnectionResetError:
                    logger.error('Could not run job. Maybe broker credentials invalid?!')
        except queue.Empty:
            pass

        remove_list = []
        for job in job_list:
            if job.is_ready():
                logger.info('Teardown {}'.format(job))
                job.teardown_env()
                if job.state == Job.DONE:
                    logger.info('Job done...')
                    shutil.move(job.disc.local_path, job.out_path)
                else:
                    logger.info('Job failed...')
                remove_list.append(job)

        for job in remove_list:
            logger.info('Removing {}'.format(job))
            job_list.remove(job)

        del remove_list

        time.sleep(5)

    logger.info('Ending teardown thread')


def master(hb_config, rip_config, in_path, out_path):
    # discard possible jobs from before
    try:
        discard_all()
    except OSError:
        logger.error('Could not connect to host')
        sys.exit(-1)

    disc_list = []
    for root, dirs, files in os.walk(in_path):
        if dirs:
            logger.error('Subdirs currently not supported!')
            break
        for f in files:
            disc_list.append(Disc(os.path.join(root, f), f))

    job_queue = queue.Queue()
    hashing_done_event = threading.Event()
    teardown_thread = threading.Thread(target=master_teardown_thread, args=(job_queue, hashing_done_event))
    teardown_thread.start()

    for d in disc_list:
        logger.info('creating job {}'.format(d))
        job = Job(d, rip_config, hb_config, in_path, out_path)
        job_queue.put(job, block=False)

    logger.info('Done hashing...')
    hashing_done_event.set()

    teardown_thread.join()


def parse_cfg_master(cfg_path):
    with open(cfg_path, 'r') as fd:
        try:
            data = json.load(fd)
            hb_config = HandbrakeConfig(quality      = data['hb_config']['quality'],
                                        h264_preset  = data['hb_config']['h264_preset'],
                                        h264_profile = data['hb_config']['h264_profile'],
                                        h264_level   = data['hb_config']['h264_level'],
                                        chapter_split = data['hb_config']['split_every_chapters'])
            rip_config = RipConfig(a_lang = data['rip_config']['a_tracks'],
                                   s_lang = data['rip_config']['s_tracks'],
                                   len_range = (data['rip_config']['min_dur'],
                                                data['rip_config']['max_dur']),
                                   fixes = data['rip_config']['fixes'])
            in_path = data['in_path']
            out_path = data['out_path']
        except KeyError:
            sys.exit('Master config not valid.')

    return (hb_config, rip_config, in_path, out_path)


def parse_cfg_slave(cfg_path):
    with open(cfg_path, 'r') as fd:
        try:
            data = json.load(fd)
            ip = data['ip']
            user = data['user']
            password = data['password']
        except KeyError:
            sys.exit('Slave config not valid.')

    return (ip, user, password)




def rip(out_dir):
    while (1):
        name = input('Please enter disc name (empty to end): ')

        if name == '':
            sys.exit(0)

        name = name.upper()

        temp_dir = tempfile.TemporaryDirectory()
        out_path = os.path.join(out_dir, name + '.iso')

        time_started = datetime.datetime.now()

        cmd = ['dvdbackup', '-M', '-i', '/dev/dvd', '-o', temp_dir.name, '-n', name]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()

        cmd = ['genisoimage', '-dvd-video', '-o', out_path, os.path.join(temp_dir.name, name)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()

        time_done = datetime.datetime.now()

        # TODO: check ret value of dvdbackup and genisoimage
        # TODO: implement check_env

        os.system('eject')

        try:
            print('Done {} [{} GB, {}]!'.format(name, os.path.getsize(out_path) / (2**30), time_done - time_started))
        except FileNotFoundError:
            print('Failed {} [{}]'.format(name, time_done - time_started))




def list_titles(target_dir, rip_config):
    for root, dirs, files in os.walk(target_dir):
        for f in files:
            print(os.path.join(root, f), end='')
            track_list= Handbrake.scan_disc(os.path.join(root, f))
            track_list = Handbrake.filter_titles(track_list, *rip_config.len_range, rip_config.a_lang, rip_config.s_lang)
            if len(track_list) == 0:
                print("  ==> Error")
                continue
            print(" => {} matching tracks...".format(len(track_list)))
            for track in track_list:
                print(track)




def dist_brake():
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--master', dest='master',  action='store', default=None,
                        help='start dist_brake as master to distribute image files to the slaves')
    parser.add_argument('--slave',  dest='slave',   action='store', default=None,
                        help='start dist_brake as slave to process image files provided by the master')
    parser.add_argument('--rip',    dest='rip',     action='store_true', default=None,
                        help='rip DVD discs to image files')
    parser.add_argument('--list',   dest='list',    action='store', default=None,
                        help='list tracks for all images in given directory that match given configuration')
    parser.add_argument('--dir',    dest='dir',     action='store', default=None,
                        help='provide a directory to scan images from')
    args = parser.parse_args()

    # check cli arguments
    if not any((args.master, args.slave, args.rip, args.list)):
        sys.exit('Please select either master, slave, rip or list!')

    # read config files
    if args.master:
        (hb_config, rip_config, in_path, out_path) = parse_cfg_master(args.master)
    elif args.list:
        (hb_config, rip_config, in_path, out_path) = parse_cfg_master(args.list)
    elif args.slave is not None:
        (ip, user, password) = parse_cfg_slave(args.slave)

    # do something
    if args.rip:
        if args.dir is None:
            sys.exit('please provide --dir')
        rip(args.dir)
        sys.exit(0)

    if args.list:
        if args.dir is None:
            sys.exit('please provide --dir')
        list_titles(args.dir, rip_config)
        sys.exit(0)

    if args.slave:
        print('Starting as slave...')
        start_worker(ip, user, password)

    elif args.master:
        print('Starting as master... (Celery version {})'.format(Command.version))
        master(hb_config, rip_config, in_path, out_path)


if __name__ == '__main__':
    dist_brake()
