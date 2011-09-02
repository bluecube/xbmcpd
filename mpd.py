#!/usr/bin/python
# -*- coding: utf-8 -*-

# This file is part of xbmcpd.

# xbmcpd is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

# xbmcpd is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with xbmcpd.  If not, see <http://www.gnu.org/licenses/>.

import itertools
import logging
import re
import operator
import twisted.internet.reactor
import twisted.internet.protocol
import twisted.protocols.basic
from pprint import pprint

class MPDError(Exception):
    ACK_ERROR_NOT_LIST = 1
    ACK_ERROR_ARG = 2
    ACK_ERROR_PASSWORD = 3
    ACK_ERROR_PERMISSION = 4
    ACK_ERROR_UNKNOWN = 5
    ACK_ERROR_NO_EXIST = 50
    ACK_ERROR_PLAYLIST_MAX = 51
    ACK_ERROR_SYSTEM = 52
    ACK_ERROR_PLAYLIST_LOAD = 53
    ACK_ERROR_UPDATE_ALREADY = 54
    ACK_ERROR_PLAYER_SYNC = 55
    ACK_ERROR_EXIST = 56

    def __init__(self, mpd, code, text):
        self.code = code
        self.position = mpd.command_list_position
        self.command = mpd.current_command
        self.text = text

    def __unicode__(self):
        return u'ACK [{}@{}] {{{}}} {}'.format(
            self.code, self.position, self.command, self.text)


class Command:
    def __init__(self, text, mpd):
        """
        Split and unescape line of commands and arguments.
        """
        split = re.findall(ur'"((?:[^\\]|\\"|\\\\)*?)"|([^ \t]+)', text)
        split = tuple((Argument(x[0] + x[1], mpd) for x in split))

        self._text = text
        self._name = split[0].lower()
        self.args = split[1:]

        self._mpd = mpd

    def __unicode__(self):
        return self._text

    def name(self):
        """
        Return the command name (first item on the line in lowercase).
        """
        return self._name

    def arg_count_exception(self):
        """
        Prepare an exception complaining about number of arguments.
        """
        return MPDError(self._mpd, MPDError.ACK_ERROR_ARG,
            u'wrong number of arguments for "{}"'.format(self._mpd.current_command))

    def check_arg_count(self, min_count, max_count = None):
        """
        Check that argument count is between min_count and max_count or
        raise an mpd error.
        """
        if not max_count:
            max_count = min_count

        if len(self.args) < min_count or len(self.args) > max_count:
            raise self.arg_count_exception()

class Argument(unicode):
    def __new__(cls, escaped, mpd):
        self = unicode.__new__(cls, re.sub(ur'\\("|\\)', ur'\1', escaped))
        self._mpd = mpd
        return self

    def _exception(self, text):
        raise MPDError(self._mpd, MPDError.ACK_ERROR_ARG, text)

    def as_range(self):
        """
        Convert mpd range from string to a dictionary suitable as limits field
        for xbmc.
        """
        try:
            split = self.split(':')
            if len(split) == 1:
                start = int(self)
                end = start + 1
            elif len(split) == 2:
                start = int(split[0])
                end = int(split[1])
            else:
                self._exception(u'need a range')

            return {'start': start, 'end': end}
        except ValueError:
            self._exception(u'need a number')

    def as_int(self):
        """
        Convert text to int, or raise MPD error if this fails.
        """
        try:
            return int(self)
        except ValueError:
            self._exception('need a number')

    def as_bool(self):
        """
        Convert "0" or "1" to bool or raise mpd error.
        """
        if self == '0':
            return False
        elif self == '1':
            return True
        else:
            self._exception('boolean (0/1) expected')


class MPD(twisted.protocols.basic.LineOnlyReceiver):
    """
    A MusicPlayerDaemon Server emulator.
    """

    SUPPORTED_COMMANDS = {'status', 'stats', 'pause', 'play',
        'next', 'previous', 'lsinfo', 'add', 'addid', 'find', 'search',
        'deleteid', 'setvol', 'clear', 'currentsong',
        'list', 'count', 'command_list_ok_begin',
        'command_list_end', 'commands', 'close',
        'notcommands', 'outputs', 'tagtypes',
        'playid','stop','seek', 'playlistinfo', 'playlistid',
        'plchanges', 'plchangesposid', 'idle',
        'listall', 'listallinfo'}

    # Tags that we support.
    # MPD tag -> XBMC tag
    # MPD tags must be capitalized!
    MPD_TAG_TO_XBMC_TAG = {
        'Artist': 'artist',
        'Album': 'album',
        'Title': 'title',
        'Track': 'track',
        'Genre': 'genre',
        'Date': 'year',
        'Time': 'duration'}

    XBMC_TAG_TO_MPD_TAG = {v:k for k, v in MPD_TAG_TO_XBMC_TAG.items()}

    def __init__(self):
        self.delimiter = '\n'
        self.command_list = []
        self.command_list_ok = False
        self.command_list_started = False
        self.command_list_position = 0
        self.current_command = ''
        self.playlist_id = 1
        self.last_playlist = None
        self.idle_mode = False

    @property
    def playlist(self):
        pl = self.xbmc.get_current_playlist()
        if pl != self.last_playlist:
            self.last_playlist = pl;
            self.playlist_id += 1
        return pl
        
    def _xbmc_path_to_mpd_path(self, path):
        """
        Converts a path that xbmc uses (based at filesystem root)
        to path format for mpd (relative to music path).
        """
        assert path.startswith(self.musicpath)

        path = path[len(self.musicpath):]
        path = path.strip(self.xbmc.path_sep)
        path = path.replace(self.xbmc.path_sep, '/')

        return path

    def _mpd_path_to_xbmc_path(self, path):
        """
        Converts a path suitable for MPD to path for XBMC
        Almost inverse for _xbmc_path_to_mpd_path()
        """

        path = path.replace('/', self.xbmc.path_sep)
        path = self.musicpath + self.xbmc.path_sep + path
        return path

    def _send_lists(self, datalist):
        """
        Pushes a list of information to the client.
        """
        for pair in datalist:
            self._send_line(u"{}: {}".format(pair[0], pair[1]))

    def _send_song(self, song, pos = None, ident = None):
        """
        Sends a single song and its metadata from an XBMC song object.
        """
        lines = [('file', self._xbmc_path_to_mpd_path(song['file']))]
        for xbmctag, value in song.items():
            if xbmctag in self.XBMC_TAG_TO_MPD_TAG:
                lines.append((self.XBMC_TAG_TO_MPD_TAG[xbmctag], value))

        if pos != None:
            lines.append(('Pos', pos))

        if ident != None:
            lines.append(('Id', ident))
            
        self._send_lists(lines)

    def _send_path(self, label, xbmc_path):
        """
        Send 'label: path' to client.
        """
        self._send_lists([(label, self._xbmc_path_to_mpd_path(xbmc_path))])

    def _process_command_list(self):
        try:
            for i, command in enumerate(self.command_list):
                logging.debug(u'command {} of {}: {}'.format(
                    i, len(self.command_list), unicode(command)))

                #for nice error messages:
                self.command_list_position = i
                self.current_command = command.name()

                if command.name() not in self.SUPPORTED_COMMANDS:
                    self.current_command = ''
                    raise MPDError(self, MPDError.ACK_ERROR_UNKNOWN,
                        u'unknown command "{}"'.format(command.name()))

                #actually handle the command
                getattr(self, command.name())(command)

                if self.command_list_ok:
                    self._send_line(u'list_OK')
        except MPDError as e:
            logging.error(e.text + u' ({})'.format(unicode(command)))
            self._send_line(unicode(e))
        except Exception as e:
            logging.critical(u'Caught an exception!', exc_info=True)
            self._send_line(unicode(MPDError(
                self, MPDError.ACK_ERROR_SYSTEM, u'Internal server error, sorry.')))
        else:
            if not self.idle_mode:
                logging.debug(u'OK')
                self._send_line('OK')

    def _send_line(self, line):
        encoded = line.encode('utf8')
        self.sendLine(encoded)

    def connectionMade(self):
        self._send_line(u'OK MPD 0.16.0')

    def lineReceived(self, data):
        """
        Receives data and takes the specified actions.
        """

        command = Command(data.rstrip('\r').decode(u'utf8'), self)

        if self.idle_mode:
            if command.name() == u'noidle':
                self._noidle([])
        elif command.name() == u'command_list_begin':
            logging.debug(u'command list started')
            self.command_list = []
            self.command_list_started = True
            self.command_list_ok = False
        elif command.name() == u'command_list_ok_begin':
            logging.debug(u'command list started')
            self.command_list = []
            self.command_list_started = True
            self.command_list_ok = True
        elif command.name() == u'command_list_end':
            logging.debug(u'command list ended')
            self._process_command_list()
            self.command_list_started = False
            self.command_list_ok = False
        elif self.command_list_started:
            self.command_list.append(command)
        else:
            self.command_list = [command]
            self._process_command_list()

    def idle(self, command):
        """
        Start the idle mode.
        By setting the self.idle_mode flag this command gets a special
        treatment -- 'OK' isn't sent after this is processed.
        """
        command.check_arg_count(0)

        if self.command_list_started:
            raise MPDError(MPDError.ACK_ERROR_SYSTEM, 
                u'idle inside command list is stupid')

        self.idle_mode = True

    def _noidle(self, changed):
        """
        Cancel running idle command.
        """
        assert self.idle_mode

        logging.debug(u'wake up (' + u', '.join(changed) + u')')

        self._send_lists(('changed', subsystem) for subsystem in changed)
        self.idle_mode = False
        self._send_line('OK')

    def playlistinfo(self, command):
        command.check_arg_count(0, 1)

        playlist = self.playlist

        if len(command.args) == 1:
            limits = command.args[0].as_range()

            for pos, song in enumerate(playlist[limits['start']:limits['end']]):
                pos += limits['start']
                self._send_song(song, pos, pos)
            
        else:
            for pos, song in enumerate(playlist):
                self._send_song(song, pos, pos)

    def playlistid(self, command):
        self.playlistinfo(command)

    def plchanges(self, command):
        """
        Send a whole playlist.
        There should be some work with playlist versioning here,
        we don't care and say that everything is always changed.
        """
        command.check_arg_count(1)
        for pos, song in enumerate(self.playlist):
            self._send_song(song, pos, pos)
        
    def plchangesposid(self, command):
        """
        Send numbers from 0 to length of playlist - 1.
        There should be some work with playlist versioning here,
        we don't care and say that everything is always changed.
        """
        command.check_arg_count(1)
        for i in range(len(self.playlist)):
            self._send_lists([('cpos', i), ('Id', i)])

    def status(self, command):
        """
        Player status from xbmc.
        """
        command.check_arg_count(0)
    
        playlist = self.playlist
        playlist_state = self.xbmc.playlist_state
        time = self.xbmc.get_time()
        volume = self.xbmc.get_volume()

        
        self._send_lists([
            ('volume', volume),
            ('consume', 0),
            ('playlist', self.playlist_id),
            ('playlistlength', len(playlist))])

        if playlist_state is None or time is None:
            self._send_lists([
                ('single', 0),
                ('repeat', 0),
                ('random', 0),
                ('state', 'stop')])
            return

        if playlist_state['paused']:
            state = 'pause'
        elif playlist_state['playing']:
            state = 'play'
        else:
            state = 'stop'

        if playlist_state['repeat'] == 'all':
            self._send_lists([
                ('repeat', 1),
                ('single', 0)])
        elif playlist_state['repeat'] == 'one':
            self._send_lists([
                ('repeat', 1),
                ('single', 1)])
        else:
            self._send_lists([
                ('repeat', 0),
                ('single', 0)])
            
        self._send_lists([
            ('state', state),
            ('song', playlist_state['current']),
            ('songid', playlist_state['current']),
            ('time', '{}:{}'.format(*time))])

    def stats(self, command):
        """
        Fetches library statistics from xbmc.
        """
        playtime = 0

        songs = self.xbmc.list_songs()
        artists = set()
        albums = set()

        for song in songs:
            playtime += song['duration']
            artists.add(song['artist'])
            albums.add(song['album'])

        self._send_lists([
            ('songs', len(songs)),
            ('artists', len(artists)),
            ('albums', len(albums)),
            ('db_playtime', playtime)])

    def tagtypes(self, command):
        """
        Sends a list of supported tagtypes.
        """
        command.check_arg_count(0)
        self._send_lists(
            (('tagtype', tag) for tag in self.MPD_TAG_TO_XBMC_TAG.keys()))

    def commands(self, command):
        """
        Sends a list of supported commands.
        """
        command.check_arg_count(0)
        self._send_lists((('command', cmd) for cmd in self.SUPPORTED_COMMANDS))

    def outputs(self, command):
        """
        Sends a list of configured outputs.
        """
        command.check_arg_count(0)
        templist = [['outputid', 0],
                    ['outputname', 'XBMC'],
                    ['outputenabled', 1]]
        self._send_lists(templist)

    def notcommands(self, command):
        command.check_arg_count(0)
        # don't talk about commands we don't support :-)

    def setvol(self, command):
        """
        Sets the volume.
        """
        command.check_arg_count(1)

        volume = command.args[0].as_int()

        if volume < 0 or volume > 100:
            raise MPDError(self, MPDError.ACK_ERROR_ARG, u"Invalid volume value")

        self.xbmc.set_volume(volume)

    def deleteid(self, command):
        """
        Deletes a song by it's specified id.
        """
        command.check_arg_count(1)
        song_id = command.args[0].as_int()
        self.xbmc.remove_from_playlist(song_id)

        self.xbmc.force_playlist_update()

    def add(self, command):
        """
        Adds a specified path to the playlist.
        """
        command.check_arg_count(1)
        path = self._mpd_path_to_xbmc_path(command.args[0])
        self.xbmc.add_to_playlist(path)

        self.xbmc.force_playlist_update()

    def addid(self, command):
        """
        Adds a specified path to the playlist and return its id.
        """
        command.check_arg_count(1, 2)

        path = self._mpd_path_to_xbmc_path(command.args[0])

        if len(command.args) == 1:
            index = len(self.playlist)
            self.xbmc.add_to_playlist(path)
            self._send_lists([('Id', index)])
        else:
            position = command.args[1].as_int()
            self.xbmc.insert_into_playlist(position, path)
            self._send_lists([('Id', position)])

        self.xbmc.force_playlist_update()

    def clear(self, command):
        command.check_arg_count(0)
        self.xbmc.clear()

        self.xbmc.force_playlist_update()

    def next(self, command):
        command.check_arg_count(0)
        self.xbmc.next()

    def previous(self, command):
        command.check_arg_count(0)
        self.xbmc.prev()

    def stop(self, command):
        command.check_arg_count(0)
        self.xbmc.stop()

    def seek(self, command):
        """
        Seek to given song and time.
        """
        command.check_arg_count(2)

        self.xbmc.playid(command.args[0].as_int())
        self.xbmc.seekto(command.args[1].as_int())

    def playid(self, command):
        """
        Get a song by it's id and play it or play the current song.
        """
        command.check_arg_count(0, 1)

        if len(command.args) == 0:
            self.xbmc.play()
        else:
            self.xbmc.playid(command.args[0].as_int())

    def play(self, command):
        """
        Since song ids and playlist position are the same,
        this function behaves exactly like playid.
        """
        self.playid(command)

    def pause(self, command):
        """
        Pause or unpause playback.
        """
        command.check_arg_count(0, 1)

        if len(command.args) == 0 or command.args[0].as_bool():
            self.xbmc.pause()
        else:
            self.xbmc.play()

    def list(self, command):
        """
        List command.
        """
        # list genre album "Café del Mar, volumen seis" artist "A New Funky Generation"

        if len(command.args) == 0:
            raise command.arg_count_exception()

        tagtype = command.args[0].capitalize()

        if tagtype not in self.MPD_TAG_TO_XBMC_TAG:
            raise MPDError(self, MPDError.ACK_ERROR_ARG,
                u'"{}" is not known'.format(command.args[0]))
            
        if len(command.args) == 2:
            if tagtype == 'Album':
                filter_list = {'Album': command.args[1]}
            else:
                raise MPDError(self, MPDError.ACK_ERROR_ARG, 
                    u'tag type must be "Album" for 2 argument version')
        else:
            filter_list = self._make_filter(command.args[1:])

        tags = set((song[self.MPD_TAG_TO_XBMC_TAG[tagtype]] for
            song in self._filtered_songs(filter_list)))

        self._send_lists([(tagtype, tag) for tag in tags])
    
    def _make_filter(self, arguments):
        """
        Returns a tuple containing filter dictionary
        used for "list" and "find" commands.
        """
        if len(arguments) % 2 != 0:
            raise MPDError(self, MPDError.ACK_ERROR_ARG,
                u'not able to parse args')

        filter_list = []
        for rule, value in zip(arguments[0::2], arguments[1::2]):
            rule = rule.capitalize()
            if rule != 'Any' and rule != 'File' and rule not in self.MPD_TAG_TO_XBMC_TAG:
                raise MPDError(self, MPDError.ACK_ERROR_ARG,
                    u'tag type "{}" unrecognized'.format(rule))
            filter_list.append((rule, value))

        return filter_list

    def _filtered_songs(self, filter_list):
        """
        Return a list of songs that satisfy the list of filter rules.
        """

        def predicate(song):
            return self._filter_predicate(filter_list, operator.eq, song)

        return itertools.ifilter(predicate, self.xbmc.list_songs())

    def _filter_predicate(self, filter_list, compare, song):
        """
        Should the given song be selected based on the filter_list and compare function?
        """
        match = True
        for rule, value in filter_list:
            if rule == 'File' or rule == 'Filename':
                match &= (compare(value, self._xbmc_path_to_mpd_path(song['file'])))
            elif rule == 'Any':
                tmpmatch = False
                for xbmctag in self.MPD_TAG_TO_XBMC_TAG.values():
                    tmpmatch |= (compare(value, unicode(song[xbmctag])))
                match &= tmpmatch
            else:
                match &= (compare(value, unicode(song[self.MPD_TAG_TO_XBMC_TAG[rule]])))

        return match

    def find(self, command):
        """
        Find command.
        """
        # find album "Café del Mar, volumen seis" artist "A New Funky Generation"

        if len(command.args) < 2:
            raise command.arg_count_exception()

        filter_list = self._make_filter(command.args)

        for song in self._filtered_songs(filter_list):
                self._send_song(song)

    def count(self, command):
        """
        Count command.
        """
        # count album "Café del Mar, volumen seis" artist "A New Funky Generation"

        if len(command.args) < 2:
            raise command.arg_count_exception()

        filter_list = self._make_filter(command.args)

        count = 0
        playtime = 0

        for song in self._filtered_songs(filter_list):
            count += 1
            playtime += song['duration']

        self._send_lists([
            ('songs', count),
            ('playtime', playtime)])

    def search(self, command):
        """
        Search command.
        """
        # like find, but case insensitive and uses substring instead of equality

        if len(command.args) < 2:
            raise command.arg_count_exception()

        filter_list = self._make_filter(command.args)

        def contains_lcase(a, b):
            return a.lower() in b.lower()

        for song in self.xbmc.list_songs():
            if self._filter_predicate(filter_list, contains_lcase, song):
                self._send_song(song)

    def currentsong(self, command):
        """
        Returns informations about the current song.
        """
        command.check_arg_count(0)

        playlist = self.playlist;

        if self.xbmc.playlist_state is None:
            return

        current = self.xbmc.playlist_state['current']
        self._send_song(playlist[current], current, current)

    def lsinfo(self, command):
        """
        Returns informations about the specified path.
        """
        command.check_arg_count(0, 1)

        if len(command.args) == 1:
            path = command.args[0]
        else:
            path = ''
        path = self._mpd_path_to_xbmc_path(path)

        filelist, dirlist, pllist = self.xbmc.get_directory(path)

        for d in dirlist:
            self._send_lists([('directory',
                self._xbmc_path_to_mpd_path(d['file']))])
        for f in filelist:
            self._send_song(f)
        for pl in pllist:
            self._send_lists([('playlist',
                self._xbmc_path_to_mpd_path(pl['file']))])

        if path.strip('/') == '':
            for pl in self.xbmc.list_playlists():
                self._send_lists(['playlist', pl['label']])

    def listall(self, command):
        """
        Returns all files under the given path.
        """
        command.check_arg_count(0, 1)

        if len(command.args) == 1:
            path = command.args[0]
        else:
            path = ''
        path = self._mpd_path_to_xbmc_path(path)

        def file_fun(f):
            self._send_path('file', f['file'])

        self._walk_xbmc_files(file_fun, path)

    def listallinfo(self, command):
        """
        Returns all files under the given path.
        """
        command.check_arg_count(0, 1)

        if len(command.args) == 1:
            path = command.args[0]
        else:
            path = ''
        path = self._mpd_path_to_xbmc_path(path)

        def file_fun(f):
            self._send_song(f)

        self._walk_xbmc_files(file_fun, path)

    def _walk_xbmc_files(self, file_fun, xbmc_path):
        """
        Walking the XBMC directory structure.
        """

        self._send_path('directory', xbmc_path)

        filelist, dirlist, pllist = self.xbmc.get_directory(xbmc_path)

        for d in dirlist:
           self._walk_xbmc_files(file_fun, d['file'])

        for f in filelist:
            file_fun(f)
        
        for p in pllist:
            self._send_path('playlist', p['file'])

    def close(self, command):
        command.check_arg_count(0)
        self.transport.loseConnection()
