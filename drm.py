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
import re
import pathlib
import logging

import drm
from drm.data import HandbrakeConfig, RipConfig, Disc, Fix, Job
import drm.handbrake as handbrake
from drm.util import *
from drm.master import master_start_server
from drm.slave import slave_start


logger = logging.getLogger('drm')


MIN_DISK_SPACE_LEFT = 15                # in gb


# TODO: support subdirs
# TODO: detect new files during runtime
# TODO: maybe add prefix to tempfile
# TODO: Check if file already fully copied (for master)
# TODO: Implement state site via flask


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
                                        h264_level=data['hb_config']['h264_level'])
            rip_config = RipConfig(a_lang=data['rip_config']['a_tracks'],
                                   s_lang=data['rip_config']['s_tracks'],
                                   len_range=(data['rip_config']['min_dur'], data['rip_config']['max_dur']))

            fixes = []
            for fix in data['fixes']:
                fixes.append(Fix(fix, data['fixes'][fix]))

            in_path = data['in_path']
            out_path = data['out_path']
    except (KeyError, json.decoder.JSONDecodeError):
        raise InvalidConfigException('Config is invalid')
    except FileNotFoundError:
        raise
    except IsADirectoryError:
        raise PathIsDirException('Config file expected, directory found')

    return (hb_config, rip_config, fixes, in_path, out_path)


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


def master(hb_config, rip_config, fixes, in_path, out_path):
    logger.info('Starting as master...')

    if len(fixes) > 0:
        logger.info('Active fixes:')
        for fix in fixes:
            logger.info('  %s', fix)

    job_queue = []

    for root, dirs, files in os.walk(in_path):
        if dirs:
            logger.error('Subdirs currently not supported!')
            break
        for f in files:
            disc = Disc(os.path.join(root, f))
            job = Job(disc, rip_config, hb_config, fixes)
            job_queue.append(job)
            logger.debug('Creating job {}'.format(job))

    logger.info('Created {} jobs'.format(len(job_queue)))

    # TODO: ip/port
    master_start_server('0.0.0.0', 5001, job_queue, out_path)


def slave(ip, port):
    logger.info('Starting as slave...')
    slave_start(ip, port)


def rip(out_dir):
    # TODO: show progress via shutil.disk_usage('/tmp/tmp.../')

    if not any([dvdbackup_check(), genisoimage_check(), eject_check()]):
        logger.error('Some necessary tool not found (dvdbackup, genisoimage, eject)')
        return

    while True:
        # Check if there is still some disk space left
        (_, _, free_mem) = shutil.disk_usage(out_dir)
        free_mem_gb = free_mem / 1024 / 1024 / 1024
        if free_mem_gb < MIN_DISK_SPACE_LEFT:
            logger.warning('Free space in out dir might not be enough')

        # Get name for image
        try:
            name = input('Please enter disc name (empty to end): ')
        except KeyboardInterrupt:
            break

        # Empty name to exit
        if name == '':
            break

        # Images are expected to use upper case (not necessary, but used here)
        name = name.upper()

        temp_dir = tempfile.TemporaryDirectory()
        out_path = os.path.join(out_dir, name + '.iso')

        if pathlib.Path(out_path).is_file():
            logger.warning('File already exists')
            continue

        time_started = datetime.datetime.now()

        rip_success = True

        try:
            dvdbackup(temp_dir.name, name)
            genisoimage(out_path, os.path.join(temp_dir.name, name))
        except KeyboardInterrupt:
            break

        time_done = datetime.datetime.now()

        # delete temp_dir explicitly, so memory gets freed right now
        del temp_dir

        # Eject disk
        eject_retval = eject()
        if not eject_retval:
            logger.error('Eject failed!')

        try:
            image_size = os.path.getsize(out_path)
        except FileNotFoundError:
            rip_success = False
            image_size = 0

        # If image is 0 byte, ripping failed, and there won't be a real image
        if image_size == 0:
            rip_success = False

        if rip_success:
            # TODO: limit print prec
            logger.info('Done {} [{} GB, {}]!'.format(name, image_size / (1024 * 1024 * 1024), time_done - time_started))
        else:
            logger.warning('Failed {} [{}]'.format(name, time_done - time_started))


def list_titles(target_dir, rip_config, fixes):
    # TODO: Maybe try libdvdread if dvdnav returns no titles?!

    use_libdvdread = False
    if 'use_libdvdread' in fixes:
        use_libdvdread = True

    for root, dirs, files in os.walk(target_dir):
        for f in files:
            track_list = handbrake.scan_disc(os.path.join(root, f), use_libdvdread)
            track_list = handbrake.filter_titles(track_list, *rip_config.len_range, rip_config.a_lang, rip_config.s_lang)
            logger.info(' => {} matching tracks...'.format(len(track_list)))
            for track in track_list:
                logger.info('  {}'.format(track))


def set_properties(target_dir):
    allowed_pattern = r'''[^a-zA-Z0-9\-() .',_!&äöüÄÖÜ\[\]]'''
    invalid_file_name_msg = 'File name invalid: '

    for root, dirs, files in os.walk(target_dir):
        for f in files:
            if os.path.splitext(f)[1] != '.mkv':
                continue

            # Check if file seems valid
            matches = re.finditer(allowed_pattern, f)
            match_pos = [e.span()[0] for e in matches]
            if match_pos:
                marker = ''.join(['^' if i in match_pos else ' ' for i in range(len(f))])
                logger.warning('%s%s', invalid_file_name_msg, f)
                logger.warning('%s%s', ' '*len(invalid_file_name_msg), marker)

            # Set mkv properties
            path = os.path.join(root, f)
            title = os.path.splitext(f)[0]
            mkvpropedit(path, title)


def help_build_epilog():
    found_hb = handbrake.check_env()
    found_dvdbackup = dvdbackup_check()
    found_geniso = genisoimage_check()
    found_eject = eject_check()
    found_mkvprop = mkvpropedit_check()

    allowed_fixes = '\n'
    for fix in Fix.allowed_fixes:
        allowed_fixes += '                 ' + fix + '\n'

    help_text = """
               Tools:
                 Handbrake      {handbrake}
                 dvdbackup      {dvdbackup}
                 genisoimage    {genisoimage}
                 eject          {eject}
                 mkvpropedit    {mkvpropedit}

               Available fixes:{allowed_fixes}

               Examples:
                 $ drm --rip isos/          # Rip DVDs to dir isos/
                 $ drm --rip master.cfg     # Rip DVDs to input directory from master.cfg
                 $ drm --list isos/         # List iso titles using default config
                 $ drm --list master.cfg    # List iso titles using config from master.cfg
                 $ drm --master master.cfg  # Start master
                 $ drm --slave slave.cfg    # Start slave
                 $ drm --prop out/          # Set properties of mkv files in directory out/
               """

    help_text = help_text.format(handbrake='Found' if found_hb else 'Not found! --slave and --list not available',
                                 dvdbackup='Found' if found_dvdbackup else 'Not found! --rip not available',
                                 genisoimage='Found' if found_geniso else 'Not found! --rip not available',
                                 eject='Found' if found_eject else 'Not found! --rip not available',
                                 mkvpropedit='Found' if found_mkvprop else 'Not found! --prop not available',
                                 allowed_fixes=allowed_fixes)

    return textwrap.dedent(help_text)


def drm_main():
    parser = argparse.ArgumentParser(description='Distributed video transcoder based on HandBrake.',
                                     epilog=help_build_epilog(),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--version', action='version', version='%(prog)s ' + drm.__version__)
    parser.add_argument('-v', '--verbose', action='count', default=0)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--master', action='store', help='start drm as master to distribute image files to the slaves')
    group.add_argument('--slave', action='store', help='start drm as slave to process image files provided by the master')
    group.add_argument('--rip', action='store', help='rip DVD discs to image files')
    group.add_argument('--list', action='store', help='list tracks for all images in given directory that match given configuration')
    group.add_argument('--prop', action='store', help='set mkv properties for files')

    args = parser.parse_args()

    # set log level
    if args.verbose == 0:
        log_level_drm = logging.INFO
        log_level_werkzeug = logging.WARNING
    elif args.verbose == 1:
        log_level_drm = logging.DEBUG
        log_level_werkzeug = logging.WARNING
    elif args.verbose == 2:
        log_level_drm = logging.DEBUG
        log_level_werkzeug = logging.INFO
    elif args.verbose == 3:
        log_level_drm = logging.DEBUG
        log_level_werkzeug = logging.DEBUG
    else:
        log_level_drm = logging.DEBUG
        log_level_werkzeug = logging.NOTSET

    # flask/werkzeug logger
    logging.getLogger('werkzeug').setLevel(log_level_werkzeug)

    # drm logger
    logger_drm = logging.getLogger('drm')
    logger_drm.setLevel(log_level_drm)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt='[%(asctime)s][%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    logger_drm.addHandler(handler)

    if args.master:
        try:
            (hb_config, rip_config, fixes, in_path, out_path) = parse_cfg_master(args.master)
        except InvalidConfigException:
            parser.error(invalid_config_get_text(expected_master=True, path=args.master))
        except FileNotFoundError:
            parser.error('Config file not found')
        except PathIsDirException:
            parser.error('File expected, directory found')

        master(hb_config, rip_config, fixes, in_path, out_path)

    elif args.slave:
        if not handbrake.check_env():
            parser.error('Handbrake not found! Please install HandBrakeCLI')

        try:
            (ip, port) = parse_cfg_slave(args.slave)
        except InvalidConfigException:
            parser.error(invalid_config_get_text(expected_master=False, path=args.slave))
        except FileNotFoundError:
            parser.error('Config file not found')
        except PathIsDirException:
            parser.error('File expected, directory found')

        slave(ip, port)

    elif args.rip:
        if not all((dvdbackup_check(), genisoimage_check(), eject_check())):
            parser.error('Necessary tools not found! Make sure dvdbackup, genisoimage and eject are installed')

        # Try if path is config file, if so, use in_path of config
        try:
            (hb_config, rip_config, fixes, in_path, out_path) = parse_cfg_master(args.rip)

            if len(fixes) > 0:
                logger.info('Active fixes:')
                for fix in fixes:
                    logger.info('  %s', fix)

            rip_dir = in_path
        except InvalidConfigException:
            parser.error(invalid_config_get_text(expected_master=True, path=args.rip))
        except FileNotFoundError:
            parser.error('Path invalid')
        except PathIsDirException:
            rip_dir = args.rip

        rip(rip_dir)

    elif args.list:
        if not handbrake.check_env():
            parser.error('Handbrake not found! Please install HandBrakeCLI')

        # Try if path is config file, if so, use in_path of config
        try:
            (hb_config, rip_config, fixes, in_path, out_path) = parse_cfg_master(args.list)
            list_dir = in_path
            list_rip_config = rip_config
        except InvalidConfigException:
            parser.error(invalid_config_get_text(expected_master=True, path=args.list))
        except FileNotFoundError:
            parser.error('Path invalid')
        except PathIsDirException:
            list_dir = args.list
            list_rip_config = RipConfig(len_range=(10, 200))
            fixes = []

        list_titles(list_dir, list_rip_config, fixes)

    elif args.prop:
        if not mkvpropedit_check():
            parser.error('mkvpropedit not found! Please install mkvpropedit')

        if not os.path.isdir(args.prop):
            parser.error('Directory expected')
        set_properties(args.prop)


if __name__ == '__main__':
    drm_main()
