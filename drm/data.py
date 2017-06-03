import os
import uuid
import tempfile
import json

import logging
logger = logging.getLogger('drm')


temp_dir = tempfile.TemporaryDirectory()


class Job(object):
    def __init__(self, disc, rip_config, hb_config, fixes):
        if not isinstance(disc, Disc):
            raise ValueError()
        if not isinstance(rip_config, RipConfig):
            raise ValueError()
        if not isinstance(hb_config, HandbrakeConfig):
            raise ValueError()

        self.disc = disc
        self.rip_config = rip_config
        self.hb_config = hb_config
        self.fixes = fixes

        self.name = str(uuid.uuid4())
        self.temp_path = os.path.join(temp_dir.name, self.name)

        self.files = []

        os.mkdir(self.temp_path)

    def __str__(self):
        return self.name


class Fix(object):
    allowed_fixes = {
        "remove_duplicate_tracks": "Tries to remove duplicate tracks, if there are the same length and directly after one another.",
        "reencode_audio":          "Reencode audio to mp3. Otherwise audio will be copied.",
        "split_every_chapters":    "Splits every title depending on the chapters. int for equal sized chunks, list of ints for different chunk lengths.",
        "use_libdvdread":          "Use libdvdread instead of libdvdnav."
    }

    def __init__(self, name, value):
        if name not in Fix.allowed_fixes:
            raise KeyError()

        self.name = name
        self.value = value

    def __eq__(self, other):
        if isinstance(other, Fix):
            return (self.name == other.name) and (self.value == other.value)
        elif isinstance(other, str):
            return self.name == other
        else:
            return False

    def __str__(self):
        return self.name

    def dump_data(self):
        return {'name': self.name, 'value': self.value}

    @classmethod
    def parse_data(cls, data):
        return cls(data['name'], data['value'])


class Chapter(object):
    def __init__(self, no, length):
        """
        Initializes a new Chapter object and specifies its number inside the title and its length in seconds.

        :param no: number of chapter in title
        :param length: length of chapter in seconds
        """
        self.no = no
        self.length = length

    def __eq__(self, other):
        if other is None:
            return False
        return (self.no == other.no) and (self.length == other.length)


class Track(object):
    def __init__(self, index, lang):
        self.index = index
        self.lang = lang

    def __eq__(self, other):
        if other is None:
            return False
        return (self.index == other.index) and (self.lang == other.lang)

    def __str__(self):
        return self.lang

    def __repr__(self):
        return self.__str__()


class Title(object):
    def __init__(self, index):
        self.index = index
        self.duration = ""
        self.a_tracks = []
        self.s_tracks = []
        self.chapters = []

    def __eq__(self, other):
        if other is None:
            return False
        return (self.duration == other.duration) and (self.a_tracks == other.a_tracks) and (self.s_tracks == other.s_tracks) and (self.chapters == other.chapters)

    def __str__(self):
        ret = "Title: {num} - {duration} - A: {a_tracks} S: {s_tracks} - {chapter} chapters"
        return ret.format(num=self.index, duration=self.duration, a_tracks=self.a_tracks,
                          s_tracks=self.s_tracks, chapter=len(self.chapters))


class Disc(object):
    def __init__(self, local_path):
        self.titles = []
        self.local_path = local_path

    def __str__(self):
        ret = self.local_path + ' (' + ''.join([str(t) for t in self.titles]) + ')'
        return ret

    def __repr__(self):
        return self.__str__()


class HandbrakeConfig(object):
    def __init__(self, preset=None, quality=20, h264_preset='medium', h264_profile='high',
                 h264_level='4.1'):
        if h264_preset not in ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow', 'placebo']:
            raise Exception('Preset invalid')
        if h264_profile not in ['baseline', 'main', 'high', 'high10', 'high422', 'high444']:
            raise Exception('Profile invalid')
        if h264_level not in ['4.1']:
            raise Exception('Level invalid')

        self.preset = preset
        self.quality = quality
        self.h264_preset = h264_preset
        self.h264_profile = h264_profile
        self.h264_level = h264_level

    def dump_data(self):
        return {'preset': self.preset, 'quality': self.quality, 'h264_preset': self.h264_preset, 'h264_profile': self.h264_profile, 'h264_level': self.h264_level}

    @classmethod
    def parse_data(cls, data):
        return cls(data['preset'], data['quality'], data['h264_preset'], data['h264_profile'], data['h264_level'])


class RipConfig(object):
    def __init__(self, a_lang=None, s_lang=None, len_range=(15, 50)):
        if a_lang is None:
            a_lang = ['eng', 'deu']
        if s_lang is None:
            s_lang = ['eng', 'deu']

        self.a_lang = a_lang
        self.s_lang = s_lang
        self.len_range = len_range

    def dump_data(self):
        return {'a_lang': self.a_lang, 's_lang': self.s_lang, 'len_range': self.len_range}

    @classmethod
    def parse_data(cls, data):
        return cls(data['a_lang'], data['s_lang'], data['len_range'])
