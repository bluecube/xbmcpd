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
        split = re.findall(ur'"((?:[^\\]|\\"|\\\\)*)"|([^ \t]+)', text)
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

    def check_arg_count(self, min_count, max_count = None):
        """
        Check that argument count is between min_count and max_count or
        raise an mpd error.
        """
        if not max_count:
            max_count = min_count

        if len(self.args) < min_count or len(self.args) > max_count:
            raise MPDError(self._mpd, MPDError.ACK_ERROR_ARG,
                u'wrong number of arguments for "{}"'.format(self._mpd.current_command))

class Argument(unicode):
    def __new__(cls, escaped, mpd):
        self = unicode.__new__(cls, re.sub(ur'\\("|\\)', ur'\1', escaped))
        self._mpd = mpd
        return self

    def _exception(self, text):
        raise MPDError(self._mpd, MPDError.ACK_ERROR_ARG, text)

    def as_range(self):
        """
        Convert mpd range from string to a python range object.
        """
        try:
            split = self.split(':')
            if len(split) == 1:
                return [self._parse_int(text)]
            elif len(split) == 2:
                return range(self._int(split[0]), self._int(split[1]))
            else:
                self._exception(u'need a range')
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

    SUPPORTED_COMMANDS = {'status', 'currentsong', 'pause', 'play',
        'next', 'previous', 'lsinfo', 'add',
        'deleteid', 'plchanges', 'setvol',
        'list', 'count', 'command_list_ok_begin',
        'command_list_end', 'commands',
        'notcommands', 'outputs', 'tagtypes',
        'playid','stop','seek','plchangesposid'}

    TAG_TYPES = ('Artist', 'Album', 'Title', 'Track', 'Name', 'Genre', 'Date')

    def __init__(self):
        self.xbmc = xbmcnp.XBMCControl(settings.XBMC_JSONRPC_URL)
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
                        u'"unknown command "{}"'.format(command.name()))

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

        command = Command(data.decode('utf8'), self)

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
            items = command.args[0].as_range()
        else:
            items = range(playlist_length)

        try:
            playlist = self.playlist_dict[self.playlist_id]
        except:
            self.plchanges(send=False)
            playlist = self.playlist_dict[self.playlist_id]
        #ugly hack ahead!
        seperated_playlist = []
        counter = 0
        templist = []
        for i in playlist:
            templist.append(i)
            counter += 1
            if counter == 10:
                seperated_playlist.append(templist)
                templist = []
                counter = 0
	if pos is not None:
	    self._send_lists(seperated_playlist[pos])
	else:
	    flattened_list = []
	    for song in seperated_playlist:
		for prop in song:
		    flattened_list.append(prop)
	    self._send_lists(flattened_list)

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
        command.check_arg_count(0)
        stats = self.xbmc.get_library_stats()
        self._send_lists([[x, stats[x]] for x in stats.keys()])


    def tagtypes(self, command):
        """
        Sends a list of supported tagtypes.
        """
        command.check_arg_count(0)
        self._send_lists((('tagtype', tag) for tag in self.TAG_TYPES))

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

    def notcommands(self, commands):
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

    def delete_id(self, song_id):
        """
        Deletes a song by it's specified id.
        """
        self.xbmc.remove_from_playlist(song_id)
        self.playlist_id += 1
        self._send()

    def add(self, command):
        """
        Adds a specified path to the playlist.
        """
        command.check_arg_count(1)

        path = command.args[0]
        self.xbmc.add_to_playlist(self._mpd_path_to_xbmc_path(path))
        self.playlist_id += 1

    def next(self, command):
        """
        Skip to the next song in the playlist.
        """
        command.check_arg_count(0)
        self.xbmc.next()

    def previous(self, command):
        """
        Return to the previous song in the playlist.
        """
        command.check_arg_count(0)
        self.xbmc.prev()

    def stop(self, command):
        """
        Stop playing.
        """
        command.check_arg_count(0)
        self.xbmc.stop()

    def seek(self, command):
        """
        Seek to given song and time.
        """
        command.check_arg_count(2)

        self.xbmc.playid(song_id)
        self.xbmc.seekto(seconds)

        self._send()

    def playid(self, song_id):
        """
        Get a song by it's id and play it.
        """
        self.xbmc.playid(song_id)
        self._send()

    def playpause(self):
        """
        Toggle play or pause.
        """
        self.xbmc.playpause()
        self._send()

    def list_dates(self):
        """
        Lists dates from all albums.

        Uses _send_lists() to push data to the client
        """
        dates = self.xbmc.list_dates()
        self._send_lists((('Date', x) for x in dates))

    def list_album_date(self, album):
        """
        Get the specified album's date.

        Uses _send_lists() to push data to the client
        """
        date = self.xbmc.list_album_date(album)
        self._send_lists([['Date', date]])

    def list_albums(self):
        """
        Creates a list of all albums.

        Uses _send_lists() to push data to the client
        """
        albums = self.xbmc.list_albums()
        self._send_lists([('ALbum', x['label']) for x in albums])

    def list_album_artist(self, artist):
        """
        Create a list of all albums from the specified artist.

        Uses _send_lists() to push data to the client
        """
        albums = self.xbmc.list_artist_albums(artist)
        self._send_lists([('ALbum', x['label']) for x in albums])

    def count_artist(self, artist):
        """
        Returns the number of all songs in the library and the total playtime.

        Uses _send_lists() to push data to the client
        """
        count = self.xbmc.count_artist(artist)
        self._send_lists([['songs', count[0]],
                          ['playtime', count[1]]])

    def list_artists(self):
        """
        Fetches a list of all artists.

        Uses _send_lists() to push data to the client
        """
        artists = self.xbmc.list_artists()
        self._send_lists([('Artist', x['label']) for x in artists])

    def list_genres(self):
        """
        Fetches a list of all genres.

        Uses _send_lists() to push data to the client
        """
        genres = self.xbmc.list_artists()
        self._send_lists([('Genre', x['label']) for x in genres])

    def plchanges(self, old_playlist_id=0, send=True):
        """
        Returns a list of playlist changes.

        Uses _send_lists() to push data to the client
        """
        #set(L1) ^ set(L2)
        playlist = self.xbmc.get_current_playlist()
        playlistlist = []

        pos = 0
        if playlist != [None]:
            for song in playlist:
                playlistlist.append(['file', song['file'].replace(self.musicpath, '')])
                if 'duration' in song:
                    playlistlist.append(['Time', song['duration']])
                if 'artist' in song:
                    playlistlist.append(['Artist', song['artist']])
                if 'title' in song:
                    playlistlist.append(['Title', song['title']])
                if 'album' in song:
                    playlistlist.append(['Album', song['album']])
                if 'track' in song:
                    playlistlist.append(['Track', song['track']])
                if 'year' in song:
                    playlistlist.append(['Date', song['year']])
                if 'genre' in song:
                    playlistlist.append(['Genre', song['genre']])
                playlistlist.append(['Pos', pos])
                playlistlist.append(['Id', pos])
                pos += 1

            self.playlist_dict[self.playlist_id] = playlistlist
            old_playlist = (tuple(info) for info in self.playlist_dict[old_playlist_id])
            diff = []
            for plinfo in playlistlist:
                if tuple(plinfo) not in old_playlist:
                    diff.append(plinfo)
            #plchanges = set(self.playlist_dict[old_playlist_id]) ^ set(playlistlist)
            if send:
                self._send_lists(diff)
        else:
            self._send()

    def plchangesposid(self, old_playlist_id=0, send=True):
        """
        This should actually not call plchanges.
        The correct implementation would be:

        "This function only returns the position and the id of the changed song,
        not the complete metadata. This is more bandwidth efficient."

        But it shall work for now - TODO : As stated above !
        """

        self.plchanges(old_playlist_id,send)

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

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format=u'%(asctime)s %(message)s', datefmt=u'%x %X')

    factory = twisted.internet.protocol.ServerFactory()
    factory.protocol = MPD
    twisted.internet.reactor.listenTCP(settings.MPD_PORT, factory)
    twisted.internet.reactor.run()
