import os
import sys
import json
import time
import datetime
import logging

from drm.data import Title, Track, Chapter
from drm.util import popen_wrapper


logger = logging.getLogger('drm')


HANDBRAKE_CLI_BIN = 'HandBrakeCLI'


def check_env():
    try:
        # TODO: This command leaves a dir in the /tmp dir. See also: https://github.com/HandBrake/HandBrake/issues/557
        (retval, stdout, stderr) = popen_wrapper([HANDBRAKE_CLI_BIN, '--version'])
        return retval == 0
    except FileNotFoundError:
        return False


def scan_disc(disc_path, use_libdvdread=False):
    # TODO: detect if disc_path does not exist
    # TODO: accept disc as argument
    # TODO: Maybe try libdvdread if dvdnav returns no titles?!

    title_list_key = 'JSON Title Set:'

    logger.info('Scanning %s...' % (disc_path))
    cmd = [HANDBRAKE_CLI_BIN, '-i', disc_path, '--json', '-t', '0']

    if use_libdvdread:
        cmd.extend(['--no-dvdnav'])

    try:
        (retval, stdout, stderr) = popen_wrapper(cmd, timeout=60)
    except TimeoutExpired:
        logger.error('Scanning failed (timeout)')
        return []

    if stdout.find(title_list_key) == -1:
        logger.error('Scanning failed (no title set output)')
        return []

    stdout = stdout[stdout.find(title_list_key) + len(title_list_key):]
    data = json.loads(stdout)
    titles = []
    for title in data['TitleList']:
        title_temp = Title(int(title['Index']))
        title_temp.duration = datetime.timedelta(hours=title['Duration']['Hours'], minutes=title['Duration']['Minutes'], seconds=title['Duration']['Seconds'])
        for a_track_idx, a_track in enumerate(title['AudioList']):
            title_temp.a_tracks.append(Track(a_track_idx + 1, a_track['LanguageCode']))
        for s_track_idx, s_track in enumerate(title['SubtitleList']):
            title_temp.s_tracks.append(Track(s_track_idx + 1, s_track['LanguageCode']))
        for chapter_idx, chapter in enumerate(title['ChapterList']):
            chapter_length = chapter['Duration']['Hours'] * 3600 + chapter['Duration']['Minutes'] * 60 + chapter['Duration']['Seconds']
            title_temp.chapters.append(Chapter(chapter_idx + 1, chapter_length))
        titles.append(title_temp)
    return titles


def filter_titles(title_list, min_time, max_time, a_lang_list, s_lang_list):
    iso639_alt_lut = {
        'alb': 'sqi', 'arm': 'hye', 'baq': 'eus', 'bod': 'tib', 'bur': 'mya',
        'ces': 'cze', 'chi': 'zho', 'cym': 'wel', 'deu': 'ger', 'dut': 'nld',
        'fas': 'per', 'fra': 'fre', 'geo': 'kat', 'gre': 'ell', 'ice': 'isl',
        'mac': 'mkd', 'mao': 'mri', 'may': 'msa', 'ron': 'rum', 'slk': 'slo'
    }
    iso639_alt_lut.update({v: k for k, v in iso639_alt_lut.items()})

    min_time = datetime.timedelta(minutes=min_time)
    max_time = datetime.timedelta(minutes=max_time)

    a_lang_list = a_lang_list + [iso639_alt_lut[e] for e in a_lang_list if e in iso639_alt_lut]
    s_lang_list = s_lang_list + [iso639_alt_lut[e] for e in s_lang_list if e in iso639_alt_lut]

    ret = []
    for t in title_list:
        if min_time < t.duration < max_time:
            t.a_tracks = [a for a in t.a_tracks if a.lang in a_lang_list]
            t.s_tracks = [s for s in t.s_tracks if s.lang in s_lang_list]
            ret.append(t)
    return ret


def _build_cmd_line(input_file, output, title, a_tracks, s_tracks, preset=None, quality=20,
                    h264_preset='medium', h264_profile='high', h264_level='4.1', chapters=None, reencode_audio=False, use_libdvdread=False):
    if h264_preset not in ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow', 'placebo']:
        raise Exception('Preset invalid')
    if h264_profile not in ['baseline', 'main', 'high', 'high10', 'high422', 'high444']:
        raise Exception('Profile invalid')
    if h264_level not in ['1.0', '1b', '1.1', '1.2', '1.3', '2.0', '2.1', '2.2', '3.0', '3.1', '3.2', '4.0', '4.1', '4.2', '5.0', '5.1', '5.2']:
        raise Exception('Level invalid')

    cmd = [HANDBRAKE_CLI_BIN]
    cmd.extend(['-i', input_file])
    cmd.extend(['-o', output])
    cmd.extend(['-t', str(title)])
    cmd.extend(['-a', _tracks_to_csl(a_tracks)])
    cmd.extend(['-s', _tracks_to_csl(s_tracks)])
    if chapters:
        # add parameter for chapter range defined by a given tuple
        cmd.extend(['-c', '{}-{}'.format(*chapters)])
    if preset is not None:
        cmd.extend(['-Z', preset])
    cmd.extend(['-f', 'mkv'])
    cmd.extend(['-m'])
    cmd.extend(['-e', 'x264'])
    cmd.extend(['-q', str(quality)])
    if reencode_audio:
        cmd.extend(['-E', 'mp3'])
    else:
        cmd.extend(['-E', 'copy'])
    cmd.extend(['--audio-fallback', 'ffac3'])
    cmd.extend(['--loose-anamorphic'])
    cmd.extend(['--modulus', '2'])
    cmd.extend(['--decomb'])
    cmd.extend(['--x264-preset', h264_preset])
    cmd.extend(['--x264-profile', h264_profile])
    cmd.extend(['--h264-level', h264_level])

    if use_libdvdread:
        cmd.extend(['--no-dvdnav'])

    return cmd


def _encode_title(hb_config, rip_config, fixes, in_path, out_path, title, chapters=None):
    title_path = ''
    if chapters is None:
        logger.info('Encoding title {}'.format(title.index))
        title_path = os.path.basename(in_path) + '.' + str(title.index) + '.mkv'

    else:
        logger.info('Encoding title {} chapters {}-{}'.format(title.index, chapters[0], chapters[1]))
        title_path = os.path.basename(in_path) + '.' + str(title.index) + '.' + str(chapters[0]) + '.mkv'

    title_out_path = os.path.join(out_path, title_path)

    reencode_audio = False
    if 'reencode_audio' in fixes:
        reencode_audio = True

    use_libdvdread = False
    if 'use_libdvdread' in fixes:
        use_libdvdread = True

    cmd = _build_cmd_line(in_path, title_out_path, title.index, title.a_tracks, title.s_tracks,
                          quality=hb_config.quality, h264_preset=hb_config.h264_preset,
                          h264_profile=hb_config.h264_profile, h264_level=hb_config.h264_level,
                          chapters=chapters, reencode_audio=reencode_audio, use_libdvdread=use_libdvdread)

    (retval, stdout, stderr) = popen_wrapper(cmd)

    return title_path


def encode_titles(hb_config, rip_config, fixes, titles, in_path, out_path):
    ret = []

    # Special case fix 'split_every_chapters'
    if 'split_every_chapters' in fixes:
        if isinstance(rip_config.fixes['split_every_chapters'], int):
            # TODO: Fix last chapter set, if length is not divisible by split_step (works currently, but isn't very nice)
            for title in titles:
                no_chapters = len(title.chapters)
                split_step = fixes['split_every_chapters']
                for i in range(1, no_chapters + 1, split_step):
                    title_path = _encode_title(hb_config, rip_config, fixes, in_path, out_path, title, chapters=(i, i + split_step - 1))
                    ret.append(title_path)

        elif isinstance(fixes['split_every_chapters'], list):
            chunks = [1]
            for chunk in fixes['split_every_chapters']:
                chunks.append(chunks[-1] + chunk)

            chunk_tuples = []
            for i in range(0, len(chunks) - 1):
                chunk_tuples.append((chunks[i], chunks[i + 1] - 1))

            for title in titles:
                for chunk in chunk_tuples:
                    title_path = _encode_title(hb_config, rip_config, fixes, in_path, out_path, title, chapters=chunk)
                    ret.append(title_path)

        else:
            sys.exit('split_every_chapters parameter must be int or list of ints')

        # Early return, because fix is done
        return ret

    # Normal case
    for title in titles:
        title_path = _encode_title(hb_config, rip_config, fixes, in_path, out_path, title)
        ret.append(title_path)

    return ret


def _tracks_to_csl(track_list):
    return ','.join([str(track.index) for track in track_list])


def remove_duplicate_tracks(titles):
    """Workaroud for stupid DVDs, that have identical copies of the same
    tracks. Might throw away some false positives, since only title
    duration and tracks are compared. This only detects duplicate titles
    directly one after another."""
    ret = []
    last = None
    for track in titles:
        if track != last:
            ret.append(track)
        last = track

    return ret
