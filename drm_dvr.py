#!/usr/bin/env python3

import argparse
import os
import re
import sys
import subprocess
import codecs
import logging
import textwrap
import json
import tempfile

import drm
from drm.util import popen_wrapper

import schnipp.schnipp as schnipp


logger = logging.getLogger('drm')


FFMPEG_BIN = 'ffmpeg'
FFPLAY_BIN = 'ffplay'

input_file_pattern = r'''aufnahme[0-9]{2}.trp'''
concat_file_name = 'concat.mp4'
cutlist_file_name = 'cutlist.txt'
cfg_file_name = 'drm_dvr.cfg'
output_file_name = 'out.mkv'


class EncodeConfig(object):
    def __init__(self, path=None):
        if path is None:
            self.cutlist = []
            self.crop = None
            self.delogo = None
        else:
            with open(path, 'r') as fd:
                data = json.load(fd)
            self.cutlist = data['cutlist']
            self.crop = data['crop']
            self.delogo = data['delogo']

    def dumps(self):
        return json.dumps({'cutlist': self.cutlist, 'crop': self.crop, 'delogo': self.delogo}, indent=2)


def ffmpeg_check():
    try:
        (retval_ffmpeg, _, _) = popen_wrapper([FFMPEG_BIN, '-version'])
        (retval_ffplay, _, _) = popen_wrapper([FFPLAY_BIN, '-version'])
        return (retval_ffmpeg == 0) and (retval_ffplay == 0)
    except FileNotFoundError:
        return False


def build_ffmpeg_filter(cfg, verbose):
    filter_cmd = []

    if cfg.delogo:
        if verbose:
            filter_cmd.append('delogo=show=1:x={}:y={}:w={}:h={}'.format(cfg.delogo[0], cfg.delogo[1], cfg.delogo[2], cfg.delogo[3]))
        else:
            filter_cmd.append('delogo=show=0:x={}:y={}:w={}:h={}'.format(cfg.delogo[0], cfg.delogo[1], cfg.delogo[2], cfg.delogo[3]))

    if cfg.crop:
        filter_cmd.append('crop=in_w-{}:in_h-{}'.format(cfg.crop[0], cfg.crop[1]))

    if filter_cmd:
        return ['-vf', '{}'.format(', '.join(filter_cmd))]
    else:
        return []


def init(path):
    rec_file_pattern = re.compile(input_file_pattern)
    files = os.listdir(path)
    files = sorted(filter(rec_file_pattern.match, files))
    files = [os.path.join(path, f) for f in files]

    if not files:
        logger.error('no input files found')
        return

    #ffmpeg -i 'concat:aufnahme00.trp|aufnahme01.trp' -codec copy concat.mp4
    cmd = [FFMPEG_BIN, '-nostdin', '-i', 'concat:{}'.format('|'.join(files)), '-codec', 'copy', os.path.join(path, concat_file_name)]
    (retval, stdout, stderr) = popen_wrapper(cmd)
    if retval:
        logger.warning('ffmpeg failed. Directory {} already initialized?'.format(path))
        return

    cfg = EncodeConfig()
    with open(os.path.join(path, cfg_file_name), 'w') as fd:
        fd.write(cfg.dumps())


def init_dir(path):
    info_path = os.path.join(path, 'info.xml')
    if os.path.isfile(info_path):
        init(os.path.join(path, '~aufnahme'))
    else:
        for d in os.listdir(path):
            entry_path = os.path.join(path, d)
            info_path = os.path.join(entry_path, 'info.xml')
            if os.path.isfile(info_path):
                init(os.path.join(entry_path, '~aufnahme'))


def preview(path):
    info_path = os.path.join(path, 'info.xml')
    if not os.path.isfile(info_path):
        logger.error('invalid preview path')
        return

    path = os.path.join(path, '~aufnahme')
    cfg = EncodeConfig(os.path.join(path, cfg_file_name))

    # ffplay -vf "delogo=x=636:y=84:w=27:h=42, crop=in_w:in_h-152" concat.mp4
    cmd = [FFPLAY_BIN]
    cmd += build_ffmpeg_filter(cfg, True)
    cmd.append(os.path.join(path, concat_file_name))
    (retval, stdout, stderr) = popen_wrapper(cmd)


def encode(path):
    print('Encoding {}'.format(path))

    cfg = EncodeConfig(os.path.join(path, cfg_file_name))
    cutlist_path = os.path.join(path, cutlist_file_name)

    with open(cutlist_path, 'w') as fd:
        for cut in cfg.cutlist:
            fd.write('file concat.mp4\n')
            fd.write('inpoint {}\n'.format(cut[0]))
            fd.write('outpoint {}\n'.format(cut[1]))

    # ffmpeg -f concat -i list.txt -vf "delogo=x=636:y=84:w=27:h=42, crop=in_w:in_h-152" -c:v libx264 -preset slow -crf 22 -c:a copy out.mkv
    cmd = [FFMPEG_BIN, '-nostdin', '-f', 'concat', '-i', cutlist_path]
    cmd += build_ffmpeg_filter(cfg, False)
    cmd += ['-c:v', 'libx264', '-preset', 'slow', '-crf', '22', '-c:a', 'copy', os.path.join(path, output_file_name)]
    (retval, stdout, stderr) = popen_wrapper(cmd)

    if retval:
        logger.error('ffmpeg failed. Does output file ({}) already exist?'.format(os.path.join(path, output_file_name)))
        return


def encode_dir(path):
    info_path = os.path.join(path, 'info.xml')
    if os.path.isfile(info_path):
        encode(os.path.join(path, '~aufnahme'))
    else:
        for d in sorted(os.listdir(path)):
            entry_path = os.path.join(path, d)
            info_path = os.path.join(entry_path, 'info.xml')
            if os.path.isfile(info_path):
                encode(os.path.join(entry_path, '~aufnahme'))


def help_build_epilog():
    help_text = """
               Examples:
                 $ drm_dvr --init /some/dir/
                 $ drm_dvr --edit /some/dir/
                 $ drm_dvr --preview /some/dir/ --delogo x=100:y=100:w=10:h=10 --crop in_w-20:in_h-152
                 $ drm_dvr --encode /some/dir/ --delogo x=100:y=100:w=10:h=10 --crop in_w-20:in_h-152
               """
    return textwrap.dedent(help_text)


def drm_dvr_main():
    if not ffmpeg_check():
        logger.error('ffmpeg not found')
        return

    parser = argparse.ArgumentParser(description='Util to convert DVR recordings. This depends highly on the used DVR recorder and probably has to be adapted.',
                                     epilog=help_build_epilog(),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--version', action='version', version='%(prog)s ' + drm.__version__)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--init', action='store', help='initialize DVR recording for encoding')
    group.add_argument('--edit', action='store', help='edit concat list to remove ads')
    group.add_argument('--preview', action='store', help='preview delogo and crop filter')
    group.add_argument('--encode', action='store', help='encode DVR recording to a single file')

    args = parser.parse_args()

    if args.init:
        init_dir(args.init)
    elif args.edit:
        path = 'file://' + os.path.abspath(args.edit) + '/~aufnahme'
        schnipp.run(path)
    elif args.preview:
        preview(args.preview)
    elif args.encode:
        encode_dir(args.encode)


if __name__ == '__main__':
    drm_dvr_main()
