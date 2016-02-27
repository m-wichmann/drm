
class Track(object):
    def __init__(self, index, lang):
        self.index = index
        self.lang  = lang

    def __eq__(self, other):
        if other is None:
            return False
        return ((self.index == other.index) and (self.lang == other.lang))

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

    def __eq__(self, other):
        if other is None:
            return False
        return ((self.duration == other.duration) and (self.a_tracks == other.a_tracks) and (self.s_tracks == other.s_tracks))

    def __str__(self):
        ret = "Title: {num} - {duration} - A: {a_tracks} S: {s_tracks}"
        return ret.format(num=self.index, duration=self.duration, a_tracks=self.a_tracks, s_tracks=self.s_tracks)

class Disc(object):
    def __init__(self, local_path, remote_path):
        self.titles = []
        self.local_path = local_path
        self.remote_path = remote_path
        self.scanned = False

    def __str__(self):
        ret = self.local_path + ' (' + ''.join([str(t) for t in self.titles]) + ')'
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
    """
        Possible fixes: remove_duplicate_tracks
    """
    def __init__(self, a_lang=['eng', 'deu'], s_lang=['eng', 'deu'], len_range=(15, 50), fixes=[]):
        self.a_lang = a_lang
        self.s_lang = s_lang
        self.len_range = len_range
        self.fixes = fixes
