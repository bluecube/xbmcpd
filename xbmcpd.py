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
import twisted.internet.reactor
import twisted.internet.protocol
import twisted.protocols.basic
import xbmcnp
import settings
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


class MPD(twisted.protocols.basic.LineOnlyReceiver):
    """
    A MusicPlayerDaemon Server emulator.
    """

    SLASHES = '\\/'

    SUPPORTED_COMMANDS = {'status', 'stats', 'pause', 'play',
        'next', 'previous', 'lsinfo', 'add', 'find',
        'deleteid', 'setvol', 'clear',
        'list', 'count', 'command_list_ok_begin',
        'command_list_end', 'commands', 'close',
        'notcommands', 'outputs', 'tagtypes',
        'playid','stop','seek', 'playlistinfo', 'playlistid'}

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
        self.playlist_dict = {0 : []}
        #self.plchanges(send=False)
        self.musicpath = settings.MUSICPATH.rstrip(self.SLASHES)

    def _xbmc_path_to_mpd_path(self, path):
        """
        Converts a path that xbmc uses (based at filesystem root)
        to path format for mpd (relative to music path).
        """
        assert path.startswith(self.musicpath)
        return path[len(self.musicpath):].strip(self.SLASHES)

    def _mpd_path_to_xbmc_path(self, path):
        return self.musicpath + '/' + path.lstrip(self.SLASHES)

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
            logging.error(e.text)
            self._send_line(unicode(e))
        except Exception as e:
            logging.critical(u'Caught an exception!', exc_info=True)
            self._send_line(unicode(MPDError(
                self, MPDError.ACK_ERROR_SYSTEM, u'Internal server error, sorry.')))
        else:
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

        if command.name() == u'command_list_begin':
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

    def playlistinfo(self, command):
        command.check_arg_count(0, 1)

        playlist_length = self.xbmc.get_playlist_length()

        if len(command.args) == 1:
            limits = command.args[0].as_range()
        else:
            limits = {'start': 0, 'end': -1}

        for pos, song in enumerate(self.xbmc.get_current_playlist(limits)):
            self._send_song(song, pos, pos)

    def playlistid(self, command):
        self.playlistinfo(command)
        #TODO: Is this all right?

    def status(self, command):
        """
        Player status from xbmc.

        Uses _send_lists() to push data to the client
        """
        command.check_arg_count(0)
        status = self.xbmc.get_status()
        self._send_lists(
            itertools.chain([[x, status[x]] for x in status.keys()],
            [['volume', self.xbmc.get_volume()],
            ['consume', 0],
            ['playlist', self.playlist_id],
            ['playlistlength', self.xbmc.get_playlist_length()]]))

    def stats(self, command):
        """
        Fetches library statistics from xbmc.

        Uses _send_lists() to push data to the client
        """
        #TODO: check this.
        command.check_arg_count(0)
        stats = self.xbmc.get_library_stats()
        self._send_lists([[x, stats[x]] for x in stats.keys()])

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
                    ['outputname', 'default output'],
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
        self.playlist_id += 1

    def add(self, command):
        """
        Adds a specified path to the playlist.
        """
        command.check_arg_count(1)

        path = command.args[0]
        self.xbmc.add_to_playlist(self._mpd_path_to_xbmc_path(path))
        self.playlist_id += 1

    def clear(self, command):
        command.check_arg_count(0)
        self.xbmc.clear()

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
        Get a song by it's id and play it.
        """
        command.check_arg_count(1)
        self.xbmc.playid(command.args[0].as_int())

    def play(self, command):
        command.check_arg_count(0)
        self.xbmc.playpause()

    def pause(self, command):
        command.check_arg_count(0)
        self.xbmc.playpause()

    def list(self, command):
        """
        List command.
        """
        # list genre album "Café del Mar, volumen seis" artist "A New Funky Generation"
        #TODO: Speed this up by specialcasing the simple filters (XBMC has some filtering).

        if len(command.args) == 0:
            raise command.arg_count_exception()

        tagtype = command.args[0].capitalize()

        if len(command.args) == 2:
            if tagtype == 'Album':
                filterdict, predicate = \
                    self._make_filter(['Album', command.args[1]])
            else:
                raise MPDError(self, MPDError.ACK_ERROR_ARG, 
                    u'tag type must be "Album" for 2 argument version')
        else:
            filterdict, predicate = self._make_filter(command.args[1:])

        if tagtype in self.MPD_TAG_TO_XBMC_TAG:
            self._list_complex(predicate, tagtype)
        else:
            raise MPDError(self, MPDError.ACK_ERROR_ARG,
                u'"{}" is not known'.format(command.args[0]))
    
    def _make_filter(self, arguments):
        """
        Returns a tuple containing filter dictionary and filtering predicate
        used for "list" and "find" commands.
        """
        if len(arguments) % 2 != 0:
            raise MPDError(self, MPDError.ACK_ERROR_ARG,
                u'not able to parse args')

        filterdict = {}
        for tag, value in zip(arguments[0::2], arguments[1::2]):
            tag = tag.capitalize()
            if tag != 'Any' and tag != 'File' and tag not in self.MPD_TAG_TO_XBMC_TAG:
                raise MPDError(self, MPDError.ACK_ERROR_ARG,
                    u'tag type "{}" unrecognized'.format(tag))
            filterdict[tag] = value

        def predicate(song):
            match = True
            for rule, value in filterdict.items():
                if rule == 'file':
                    match &= (self._mpd_path_to_xbmc_path(value) == song['file'])
                elif rule == 'any':
                    tmpmatch = False
                    for xbmctag in self.MPD_TAG_TO_XBMC_TAG.values():
                        tmpmatch |= (value == song[xbmctag])
                    match &= tmpmatch
                else:
                    match &= (value == song[self.MPD_TAG_TO_XBMC_TAG[rule]])

            return match

        return filterdict, predicate

    def _list_complex(self, predicate, tagtype):
        """
        Handle complex filtering for list command.
        Downloads all songs and filters everything using the givent predicate.
        """
        tags = set((song[self.MPD_TAG_TO_XBMC_TAG[tagtype]] for
            song in self.xbmc.list_songs() if predicate(song)))

        self._send_lists([(tagtype, tag) for tag in tags])

    def find(self, command):
        """
        List command.
        """
        # find album "Café del Mar, volumen seis" artist "A New Funky Generation"
        #TODO: Speed this up by specialcasing the simple filters (XBMC has some filtering).

        if len(command.args) < 2:
            raise command.arg_count_exception()

        filterdict, predicate = self._make_filter(command.args)

        self._find_complex(predicate)

    def _find_complex(self, predicate):
        """
        Handle complex filtering for find command.
        Downloads all songs and filters everything using the givent predicate.
        """
        for song in self.xbmc.list_songs():
            if predicate(song):
                self._send_song(song)

    def currentsong(self, command):
        """
        Returns informations about the current song.

        If there is a song the following information is pushed via _send_lists():
            * File
            * Time
            * Artist
            * Title
            * Track
            * Genre
            * Position
            * ID

        Otherwise a simple 'OK' is returned via _send()
        """

        # TODO: rewrite and test this.

        command.check_arg_count(0)

        status = self.xbmc.get_current_song()
        if status == None:
            return

        self._send_lists([['file', status['Player.Filenameandpath'].replace(self.musicpath, '')],
            ['Time', status['duration']],
            ['Artist', status['MusicPlayer.Artist']],
            ['Title', status['MusicPlayer.Title']],
            ['Album', status['MusicPlayer.Album']],
            ['Track', status['MusicPlayer.TrackNumber']],
            ['Genre', status['MusicPlayer.Genre']],
            ['Pos', status['MusicPlayer.PlaylistPosition']],
            ['Id', status['MusicPlayer.PlaylistPosition']]])

    def lsinfo(self, command):
        """
        Returns informations about the specified path.
        """
        command.check_arg_count(0, 1)

        if len(command.args) == 1:
            path = command.args[0]
        else:
            path = ''

        filelist = []
        dirlist = []
        pllist = []

        for f in self.xbmc.get_directory(self._mpd_path_to_xbmc_path(path)):
            filepath = self._xbmc_path_to_mpd_path(f['file'])
            if f['filetype'] == 'directory':
                if f['file'].endswith(tuple(self.SLASHES)):
                    dirlist.append(['directory', filepath])
                else:
                    pllist.append(['playlist', filepath])
            else:
                filelist.append(['file', filepath])
                filelist.append(['Time', f['duration']])
                filelist.append(['Artist', f['artist']])
                filelist.append(['Title', f['title']])
                filelist.append(['Album', f['album']])
                filelist.append(['Track', f['track']])
                filelist.append(['Date', f['year']])
                filelist.append(['Genre', f['genre']])

        if path.lstrip(self.SLASHES) == '':
            for pl in self.xbmc.list_playlists():
                pllist.append(['playlist', pl['label']])


        self._send_lists(itertools.chain(dirlist, filelist, pllist))

    def close(self, command):
        command.check_arg_count(0)
        self.transport.loseConnection()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=u'%(asctime)s %(message)s', datefmt=u'%x %X')

    logging.debug('downloading XBMC data')
    MPD.xbmc = xbmcnp.XBMCControl(settings.XBMC_JSONRPC_URL) #only to update the static info before the first request.

    factory = twisted.internet.protocol.ServerFactory()
    factory.protocol = MPD
    twisted.internet.reactor.listenTCP(settings.MPD_PORT, factory)

    logging.info('starting MPD server at port {}'.format(settings.MPD_PORT))

    twisted.internet.reactor.run()
