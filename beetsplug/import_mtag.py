import datetime
import dateutil.parser
import json
import re
from pathlib import Path

from beets.plugins import BeetsPlugin
from beets.ui import Subcommand
from beets.library import Item, PathQuery
from beets.mediafile import MediaFile
from beets.util import syspath


class MTagDate(datetime.date):
    _mtag_date = False


class MTagLoader:
    def __init__(self, path):
        self._path = Path(path)
        self._tagset = {}

    def _resolve_path(self, path):
        if '|' in path:
            path, sub = path.split('|')
            try:
                sub = int(sub)
            except ValueError:
                raise NotImplementedError("can't deal with archives yet")
        else:
            sub = None
        path = self._path.parent / path
        path = path.resolve()
        if sub is not None and str(path).endswith('.tags'):
            resolver = self.__class__(str(path))
            for i, item in enumerate(resolver.items(), start=1):
                r_path, r_data = item
                if i == sub:
                    return resolver._resolve_path(r_path)
            raise LookupError
        elif sub is not None:
            raise Exception
        return str(path)

    def _update(self, data):
        self._tagset.update({k.casefold(): v for k, v in data.items()})
        for k, v in list(self._tagset.items()):
            if v == []:
                del self._tagset[k]
        return dict(self._tagset)

    def items(self):
        try:
            with open(self._path, 'r', encoding='utf-8-sig') as f:
                obj = json.load(f)
        except Exception:
            print(f"couldn't load as json: {self._path}")
            obj = []
        for item in obj:
            data = self._update(item)
            try:
                path = self._resolve_path(data.pop('@'))
            except NotImplementedError:
                continue
            yield (path, data)


class Converter:
    def __init__(self, *tags):
        self._tags = tags
    def decode(self, data):
        return data
    def get(self, data):
        for t in self._tags:
            try:
                v = data[t]
            except KeyError:
                continue
            return self.decode(v)
        return None
class IntConverter(Converter):
    def decode(self, data):
        return int(data)
class FloatConverter(Converter):
    def decode(self, data):
        return float(data)
class DbConverter(Converter):
    def decode(self, data):
        return float(re.sub(r'(.*) [Dd][Bb]', r'\1', data))
class ListConverter(Converter):
    def decode(self, data):
        if not isinstance(data, list):
            data = [data]
        return data[0]
class BoolConverter(Converter):
    def decode(self, data):
        return data.casefold() not in {'', '0', 'no', 'false'}
class DateConverter(Converter):
    def decode(self, data):
        try:
            v = MTagDate(int(data), 1, 1)
        except ValueError:
            v = dateutil.parser.parse(data)
            v = MTagDate(v.year, v.month, v.day)
            v._mtag_date = True
        return v


class DependentConverter:
    def __init__(self, dep):
        self.dep = dep
    def get(self, data, context):
        try:
            v = context[self.dep]
        except LookupError:
            return None
        return self.transform(v)
class Year(DependentConverter):
    def transform(self, v):
        return v.year
class Month(DependentConverter):
    def transform(self, v):
        return v.month if v._mtag_date else None
class Day(DependentConverter):
    def transform(self, v):
        return v.day if v._mtag_date else None
class DateHack(DependentConverter):
    def transform(self, v):
        return datetime.date(v.year, v.month, v.day)


AUDIO_FIELDS = ['length', 'bitrate', 'format', 'samplerate', 'bitdepth', 'channels']

TAGS = {
    'title': Converter('title'),
    'artist': ListConverter('artist'),
    'album': Converter('album'),
    'genre': ListConverter('genres', 'genre'),
    'lyricist': Converter('lyricist'),
    'composer': ListConverter('composer'),
    'composer_sort': Converter('composersort'),
    'arranger': Converter('arranger'),
    'grouping': Converter('grouping'),
    'track': IntConverter('track', 'tracknumber'),
    'tracktotal': IntConverter('tracktotal', 'trackc', 'totaltracks'),
    'disc': IntConverter('disc', 'discnumber'),
    'disctotal': IntConverter('disctotal', 'discc', 'totaldiscs'),
    'lyrics': Converter('lyrics', 'unsyncedlyrics'),
    'comments': Converter('description', 'comment'),
    'bpm': IntConverter('bpm'),
    'comp': BoolConverter('compilation'),
    'albumartist': Converter('albumartist', 'album artist'),
    'albumtype': Converter('musicbrainz_albumtype'),
    'label': ListConverter('label', 'publisher'),
    'artist_sort': Converter('artistsort'),
    'albumartist_sort': Converter('albumartistsort'),
    'asin': Converter('asin'),
    'catalognum': Converter('catalognumber'),
    'disctitle': Converter('discsubtitle'),
    'encoder': Converter('encodedby', 'encoder'),
    'script': Converter('script'),
    'language': Converter('language'),
    'country': Converter('releasecountry'),
    'albumstatus': Converter('musicbrainz_albumstatus'),
    'media': Converter('media'),
    'albumdisambig': Converter('musicbrainz_albumcomment'),
    'date': DateConverter('date', 'year'),
    'original_date': DateConverter('originaldate'),
    'artist_credit': Converter('artist_credit'),
    'albumartist_credit': Converter('albumartist_credit'),
    'mb_trackid': Converter('musicbrainz_trackid'),
    'mb_releasetrackid': Converter('musicbrainz_releasetrackid'),
    'mb_albumid': Converter('musicbrainz_albumid'),
    'mb_artistid': Converter('musicbrainz_artistid'),
    'mb_albumartistid': Converter('musicbrainz_albumartistid'),
    'mb_releasegroupid': Converter('musicbrainz_releasegroupid'),
    'acoustid_fingerprint': Converter('acoustid_fingerprint'),
    'acoustid_id': Converter('acoustid_id'),
    'rg_track_gain': DbConverter('replaygain_track_gain'),
    'rg_track_peak': FloatConverter('replaygain_track_peak'),
    'rg_album_gain': DbConverter('replaygain_album_gain'),
    'rg_album_peak': FloatConverter('replaygain_album_peak'),
    'r128_track_gain': IntConverter('r128_track_gain'),
    'r128_album_gain': IntConverter('r128_album_gain'),
    'initial_key': Converter('initialkey'),
}

DEPENDENT_TAGS = {
    'year': Year('date'),
    'month': Month('date'),
    'day': Day('date'),
    'original_year': Year('original_date'),
    'original_month': Month('original_date'),
    'original_day': Day('original_date'),
    'date': DateHack('date'),
    'original_date': DateHack('original_date'),
}


class MTagImporter(BeetsPlugin):
    def _import_mtags(self, lib, opts, args):
        path, = args
        paths = [Path(path)]
        while paths:
            p = paths.pop(0)
            for child in p.iterdir():
                if child.is_dir():
                    paths.append(child)
                    continue
                loader = MTagLoader(child)
                al = []
                for path, data in loader.items():
                    matching = lib.items(PathQuery('path', path))
                    if any(m.path == path.encode() for m in matching):
                        print('skip %r because it is already present' % path)
                        continue
                    print('add %r' % path)
                    item = Item(path=path)
                    mf = MediaFile(syspath(item.path))
                    for field in AUDIO_FIELDS:
                        v = getattr(mf, field)
                        item[field] = v
                    values = {}
                    for tag, converter in TAGS.items():
                        v = converter.get(data)
                        if v is not None:
                            values[tag] = v
                            item[tag] = v
                    for tag, converter in DEPENDENT_TAGS.items():
                        v = converter.get(data, values)
                        if v is not None:
                            item[tag] = v
                    al.append(item)
                if al:
                    #print(al)
                    try:
                        lib.add_album(al)
                    except BaseException as e:
                        import pdb; pdb.post_mortem(e.__traceback__)
                        return

    def commands(self):
        import_mtags = Subcommand('import-mtags', help="Import a directory of m-tag files")
        import_mtags.func = self._import_mtags
        return [import_mtags]
