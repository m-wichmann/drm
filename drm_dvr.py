#!/usr/bin/env python3

import argparse
import os
import re
import sys
import subprocess
import codecs
import logging
import textwrap

import drm
from drm.util import popen_wrapper


logger = logging.getLogger('drm')


FFMPEG_BIN = 'ffmpeg'
FFPLAY_BIN = 'ffplay'

input_file_pattern = r'''aufnahme[0-9]{2}.trp'''
concat_file_name = 'concat.mp4'
cutlist_file_name = 'cutlist.txt'
output_file_name = 'out.mkv'


def ffmpeg_check():
    try:
        (retval_ffmpeg, _, _) = popen_wrapper([FFMPEG_BIN, '-version'])
        (retval_ffplay, _, _) = popen_wrapper([FFPLAY_BIN, '-version'])
        return (retval_ffmpeg == 0) and (retval_ffplay == 0)
    except FileNotFoundError:
        return False


def build_ffmpeg_filter(args, verbose):
    delogo_pattern = r'''x=[0-9]+:y=[0-9*]+:w=[0-9*]+:h=[0-9*]+'''
    crop_pattern = r'''in_w(-[0-9]+)?:in_h(-[0-9]+)?'''

    filter_cmd = []

    if args.delogo:
        if not re.match(delogo_pattern, args.delogo):
            raise ValueError('delogo filter format invalid')
        if verbose:
            filter_cmd.append('delogo=show=1:{}'.format(args.delogo))
        else:
            filter_cmd.append('delogo=show=0:{}'.format(args.delogo))

    if args.crop:
        if not re.match(crop_pattern, args.crop):
            logger.info('Crop filter format currently limited')
            raise ValueError('crop filter format invalid')
        filter_cmd.append('crop={}'.format(args.crop))

    if filter_cmd:
        return ['-vf', '{}'.format(', '.join(filter_cmd))]
    else:
        return []


def init(args):
    rec_file_pattern = re.compile(input_file_pattern)
    files = os.listdir(args.init)
    files = sorted(filter(rec_file_pattern.match, files))
    files = [os.path.join(args.init, f) for f in files]

    if not files:
        logger.error('no input files found')
        return

    #ffmpeg -i 'concat:aufnahme00.trp|aufnahme01.trp' -codec copy concat.mp4
    cmd = [FFMPEG_BIN, '-nostdin', '-i', 'concat:{}'.format('|'.join(files)), '-codec', 'copy', os.path.join(args.init, concat_file_name)]
    (retval, stdout, stderr) = popen_wrapper(cmd)
    if retval:
        logger.error('ffmpeg failed. Directory already initialized?')
        return

    with open(os.path.join(args.init, cutlist_file_name), 'w') as fd:
        fd.write('# Copy block below for every part that should be included in the output.')
        fd.write('# Timestamp format: h:m:s.ms. Unused parts can be omitted.')
        fd.write('file {}\n'.format(concat_file_name))
        fd.write('inpoint 0:0:0\n')
        fd.write('outpoint 1:0:0\n')


def edit(args):
    # TODO: support different editor
    (retval, stdout, stderr) = popen_wrapper(['atom', os.path.join(args.edit, cutlist_file_name)])


def preview(args):
    # ffplay -vf "delogo=x=636:y=84:w=27:h=42, crop=in_w:in_h-152" concat.mp4
    cmd = [FFPLAY_BIN]
    try:
        cmd += build_ffmpeg_filter(args, True)
    except ValueError:
        logger.error('Filter format invalid. (e.g. --delogo=x=636:y=84:w=27:h=42 --crop=in_w:in_h-152)')
        return
    cmd.append(os.path.join(args.preview, concat_file_name))
    (retval, stdout, stderr) = popen_wrapper(cmd)


def encode(args):
    # ffmpeg -f concat -i list.txt -vf "delogo=x=636:y=84:w=27:h=42, crop=in_w:in_h-152" -c:v libx264 -preset slow -crf 22 -c:a copy out.mkv
    cmd = [FFMPEG_BIN, '-nostdin', '-f', 'concat', '-i', os.path.join(args.encode, cutlist_file_name)]
    try:
        cmd += build_ffmpeg_filter(args, False)
    except ValueError:
        logger.error('Filter format invalid. (e.g. --delogo=x=636:y=84:w=27:h=42 --crop=in_w:in_h-152)')
        return
    cmd += ['-c:v', 'libx264', '-preset', 'slow', '-crf', '22', '-c:a', 'copy', os.path.join(args.encode, output_file_name)]
    (retval, stdout, stderr) = popen_wrapper(cmd)

    if retval:
        logger.error('ffmpeg failed. Does output file ({}) already exist?'.format(os.path.join(args.encode, output_file_name)))
        return


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

    parser.add_argument('--delogo', action='store', help='remove logo from recording (used with preview and encode)')
    parser.add_argument('--crop', action='store', help='crop recording (used with preview and encode)')

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--init', action='store', help='initialize DVR recording for encoding')
    group.add_argument('--edit', action='store', help='edit concat list to remove ads')
    group.add_argument('--preview', action='store', help='preview delogo and crop filter')
    group.add_argument('--encode', action='store', help='encode DVR recording to a single file')

    args = parser.parse_args()

    if args.init:
        if args.delogo or args.crop:
            logger.warn('--delog and --crop not used with --init')
        init(args)
    elif args.edit:
        if args.delogo or args.crop:
            logger.warn('--delog and --crop not used with --edit')
        edit(args)
    elif args.preview:
        preview(args)
    elif args.encode:
        encode(args)


if __name__ == '__main__':
    drm_dvr_main()
