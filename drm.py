#!/usr/bin/env python3

import argparse
import os
import sys
import tempfile
import time
import shutil
import datetime
import json
import threading
import queue
import textwrap

from drm.data import HandbrakeConfig, RipConfig, Disc
from drm.job import Job
from drm.handbrake import Handbrake
from drm.util import *
from drm.master import master_start_server
from drm.slave import slave_start


DRM_VERSION = "2.0.0"


import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('drm')


# TODO: support subdirs
# TODO: detect new files during runtime


class InvalidConfigException(Exception):
    pass


class PathIsDirException(Exception):
    pass


def invalid_config_get_text(expected_master, path):
    # Check if a slave config was given
    try:
        if expected_master:
            parse_cfg_slave(path)
        else:
            parse_cfg_master(path)
        wrong_config_found = True
    except:
        wrong_config_found = False

    ret = 'Config file invalid'
    if wrong_config_found:
        if expected_master:
            ret = 'Config file for master expected, slave config found'
        else:
            ret = 'Config file for slave expected, master config found'

    return ret


def parse_cfg_master(cfg_path):
    try:
        with open(cfg_path, 'r') as fd:
            data = json.load(fd)

            hb_config = HandbrakeConfig(quality=data['hb_config']['quality'],
                                        h264_preset=data['hb_config']['h264_preset'],
                                        h264_profile=data['hb_config']['h264_profile'],
                                        h264_level=data['hb_config']['h264_level'],
                                        fixes=data['fixes'])
            rip_config = RipConfig(a_lang=data['rip_config']['a_tracks'],
                                   s_lang=data['rip_config']['s_tracks'],
                                   len_range=(data['rip_config']['min_dur'], data['rip_config']['max_dur']),
                                   fixes=data['fixes'])

            in_path = data['in_path']
            out_path = data['out_path']
    except (KeyError, json.decoder.JSONDecodeError):
        raise InvalidConfigException('Config is invalid')
    except FileNotFoundError:
        raise
    except IsADirectoryError:
        raise PathIsDirException('Config file expected, directory found')

    return (hb_config, rip_config, in_path, out_path)


def parse_cfg_slave(cfg_path):
    try:
        with open(cfg_path, 'r') as fd:
            data = json.load(fd)
            ip = data['ip']
            port = data['port']
    except (KeyError, json.decoder.JSONDecodeError):
        raise InvalidConfigException('Config is invalid')
    except FileNotFoundError:
        raise
    except IsADirectoryError:
        raise PathIsDirException('Config file expected, directory found')

    return (ip, port)


def master(hb_config, rip_config, in_path, out_path):
    job_queue = []

    for root, dirs, files in os.walk(in_path):
        if dirs:
            logger.error('Subdirs currently not supported!')
            break
        for f in files:
            disc = Disc(os.path.join(root, f), f)
            job = Job(disc, rip_config, hb_config, in_path, out_path)
            job_queue.append(job)
            logger.info('creating job {}'.format(job))

    # TODO: ip/port
    master_start_server('0.0.0.0', 5001, job_queue)


def rip(out_dir):
    while True:
        name = input('Please enter disc name (empty to end): ')

        if name == '':
            sys.exit(0)

        name = name.upper()

        temp_dir = tempfile.TemporaryDirectory()
        out_path = os.path.join(out_dir, name + '.iso')

        time_started = datetime.datetime.now()

        dvdbackup(temp_dir.name, name)
        genisoimage(out_path, os.path.join(temp_dir.name, name))

        time_done = datetime.datetime.now()

        # delete temp_dir explicitly, so memory gets freed
        del temp_dir

        # TODO: check ret value of dvdbackup and genisoimage
        # TODO: implement check_env

        eject()

        # TODO: rip also failed, if image is 0.0 GB

        try:
            print('Done {} [{} GB, {}]!'.format(name, os.path.getsize(out_path) / (2**30), time_done - time_started))
        except FileNotFoundError:
            print('Failed {} [{}]'.format(name, time_done - time_started))


def list_titles(target_dir, rip_config):
    use_libdvdread = False
    if "use_libdvdread" in rip_config.fixes:
        use_libdvdread = True

    for root, dirs, files in os.walk(target_dir):
        for f in files:
            print(os.path.join(root, f), end='')
            track_list = Handbrake.scan_disc(os.path.join(root, f), use_libdvdread)
            track_list = Handbrake.filter_titles(track_list, *rip_config.len_range, rip_config.a_lang, rip_config.s_lang)
            print(' => {} matching tracks...'.format(len(track_list)))
            for track in track_list:
                print('  ', track)


def set_properties(target_dir):
    for root, dirs, files in os.walk(target_dir):
        for f in files:
            if os.path.splitext(f)[1] != '.mkv':
                continue

            path = os.path.join(root, f)
            title = os.path.splitext(f)[0]

            mkvpropedit(path, title)


def help_build_epilog():
    found_hb = Handbrake.check_env()
    found_dvdbackup = dvdbackup_check()
    found_geniso = genisoimage_check()
    found_eject = eject_check()
    found_mkvprop = mkvpropedit_check()

    help_text = """
               Tools:
                 Handbrake      {handbrake}
                 dvdbackup      {dvdbackup}
                 genisoimage    {genisoimage}
                 eject          {eject}
                 mkvpropedit    {mkvpropedit}

               Examples:
                 $ drm --rip isos/          # Rip DVDs to dir isos/
                 $ drm --rip master.cfg     # Rip DVDs to input directory from master.cfg
                 $ drm --list isos/         # List iso titles using default config
                 $ drm --list master.cfg    # List iso titles using config from master.cfg
                 $ drm --master master.cfg  # Start master
                 $ drm --slave slave.cfg    # Start slave
                 $ drm --prop out/          # Set properties of mkv files in directory out/
               """

    help_text = help_text.format(handbrake="Found" if found_hb else "Not found! --slave and --list not available",
                                 dvdbackup="Found" if found_dvdbackup else "Not found! --rip not available",
                                 genisoimage="Found" if found_geniso else "Not found! --rip not available",
                                 eject="Found" if found_eject else "Not found! --rip not available",
                                 mkvpropedit="Found" if found_mkvprop else "Not found! --prop not available")

    return textwrap.dedent(help_text)


def drm_main():
    parser = argparse.ArgumentParser(description='Distributed video transcoder based on HandBrake and Celery.',
                                     epilog=help_build_epilog(),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--version', action='version', version='%(prog)s ' + DRM_VERSION)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--master', action='store', help='start drm as master to distribute image files to the slaves')
    group.add_argument('--slave', action='store', help='start drm as slave to process image files provided by the master')
    group.add_argument('--rip', action='store', help='rip DVD discs to image files')
    group.add_argument('--list', action='store', help='list tracks for all images in given directory that match given configuration')
    group.add_argument('--prop', action='store', help='set mkv properties for files')

    args = parser.parse_args()

    if args.master:
        try:
            (hb_config, rip_config, in_path, out_path) = parse_cfg_master(args.master)
        except InvalidConfigException:
            parser.error(invalid_config_get_text(expected_master=True, path=args.master))
        except FileNotFoundError:
            parser.error('Config file not found')
        except PathIsDirException:
            parser.error('File expected, directory found')

        master(hb_config, rip_config, in_path, out_path)

    elif args.slave:
        if not Handbrake.check_env():
            parser.error('Handbrake not found! Please install HandBrakeCLI')

        try:
            (ip, port) = parse_cfg_slave(args.slave)
        except InvalidConfigException:
            parser.error(invalid_config_get_text(expected_master=False, path=args.slave))
        except FileNotFoundError:
            parser.error('Config file not found')
        except PathIsDirException:
            parser.error('File expected, directory found')

        print('Starting as slave...')
        slave_start(ip, port)

    elif args.rip:
        if not all((dvdbackup_check(), genisoimage_check(), eject_check())):
            parser.error('Necessary tools not found! Make sure dvdbackup, genisoimage and eject are installed')

        # Try if path is config file, if so, use in_path of config
        try:
            (hb_config, rip_config, in_path, out_path) = parse_cfg_master(args.rip)
            rip_dir = in_path
        except InvalidConfigException:
            parser.error(invalid_config_get_text(expected_master=True, path=args.rip))
        except FileNotFoundError:
            parser.error('Path invalid')
        except PathIsDirException:
            rip_dir = args.rip

        rip(rip_dir)

    elif args.list:
        if not Handbrake.check_env():
            parser.error('Handbrake not found! Please install HandBrakeCLI')

        # Try if path is config file, if so, use in_path of config
        try:
            (hb_config, rip_config, in_path, out_path) = parse_cfg_master(args.list)
            list_dir = in_path
            list_rip_config = rip_config
        except InvalidConfigException:
            parser.error(invalid_config_get_text(expected_master=True, path=args.list))
        except FileNotFoundError:
            parser.error('Path invalid')
        except PathIsDirException:
            list_dir = args.list
            list_rip_config = RipConfig(len_range=(10, 200))

        list_titles(list_dir, list_rip_config)

    elif args.prop:
        if not mkvpropedit_check():
            parser.error('mkvpropedit not found! Please install mkvpropedit')

        if not os.path.isdir(args.prop):
            parser.error('Directory expected')
        set_properties(args.prop)


if __name__ == '__main__':
    drm_main()
