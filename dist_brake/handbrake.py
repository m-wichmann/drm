
import os
import time
import codecs
import datetime
import subprocess

from dist_brake.data import Title, Track, Chapter


import logging
logger = logging.getLogger('dist_hb')


HANDBRAKE_CLI_BIN = 'HandBrakeCLI'


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
        in_chapters = False
        title_temp = None
        title_list = []
        for line in temp:
            if (in_a_tracks or in_s_tracks or in_chapters) and (line[:4] == '  + '):
                in_s_tracks = False
                in_a_tracks = False
                in_chapters = False

            if '  + audio tracks:' in line:
                in_a_tracks = True
                continue
            elif '  + subtitle tracks:' in line:
                in_s_tracks = True
                continue
            elif '  + chapters:' in line:
                in_chapters = True
                continue
            elif "  + duration:" in line:
                temp = line[14:].split(':')
                title_temp.duration = datetime.timedelta(hours=int(temp[0]), minutes=int(temp[1]), seconds=int(temp[2]))
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
            elif in_chapters:
                # parse chapter number
                marker = line.find(':')
                if marker != -1:
                    no = int(line[6:marker])
                    # parse length and calculate seconds
                    marker = line.find('duration') + len('duration') + 1
                    t = time.strptime(line[marker:], "%H:%M:%S")
                    length = t.tm_hour*3600 + t.tm_min*60 + t.tm_sec
                    title_temp.chapters.append(Chapter(no, length))
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

    @classmethod
    def build_cmd_line(cls, input, output, title, a_tracks, s_tracks, preset=None, quality=20,
                       h264_preset='medium', h264_profile='high', h264_level='4.1', chapters=None, reencode_audio=False):
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

        return cmd


    @staticmethod
    def encode_titles(hb_config, rip_config, title_list, in_path, out_path):
        logging.info('encoding titles...')

        reencode_audio = False
        if "reencode_audio" in rip_config.fixes:
            reencode_audio = True

        ret = []
        for t in title_list:
            logging.info('encoding title {}'.format(t.index))
            # check in how much parts the title has to be endoded
            no_chapters = len(t.chapters)
            no_split = hb_config.chapter_split if hb_config.chapter_split else no_chapters
            for i in range(1, no_chapters+1, no_split):
                logging.info('encoding title {} chapters {}-{}'.format(t.index, i, i+no_split-1))
                # create output file name
                title_path = os.path.basename(in_path) + '.' + str(t.index) + '.' + str(i) + '.mkv'
                title_out_path = os.path.join(out_path, title_path)
                # build command and execute
                cmd = Handbrake.build_cmd_line(in_path, title_out_path, t.index, t.a_tracks, t.s_tracks,
                                               quality=hb_config.quality, h264_preset=hb_config.h264_preset,
                                               h264_profile=hb_config.h264_profile, h264_level=hb_config.h264_level,
                                               chapters=(i, i+no_split-1), reencode_audio=reencode_audio)
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = proc.communicate()
                stdout = codecs.decode(stdout, 'utf-8', 'replace')
                stderr = codecs.decode(stderr, 'utf-8', 'replace')
                ret.append(title_path)
        return ret

    @staticmethod
    def encode_sample(hb_config, in_path, out_path):
        logging.info('encoding sample...')

    @classmethod
    def _tracks_to_csl(cls, track_list):
        temp = ""
        for i in range(len(track_list)):
            temp += str(track_list[i].index)
            if i != len(track_list) - 1:
                temp += ','
        return temp

    @staticmethod
    def remove_duplicate_tracks(titles):
        """Workaroud for stupid DVDs, that have identical copies of the same
        tracks. Might throw away some false positives, since only title
        duration and tracks are compared."""
        ret = []
        l = None
        for t in titles:
            if t != l:
                ret.append(t)
            l = t

        return ret
