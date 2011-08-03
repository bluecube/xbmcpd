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
        self._code = code
        self._position = mpd.command_list_position
        self._command = mpd.current_command
        self._text = text

    def __str__(self):
        return 'ACK [{}@{}] {{{}}} {}'.format(
            self._code, self._position, self._command, self._text)


class Command:
    def __init__(self, text):
        """
        Split and unescape line of commands and arguments.
        """
        split = re.findall(r'"((?:[^\\]|\\"|\\\\)*)"|([^ \t]+)', text)
        self._tuple = tuple((re.sub(r'\\("|\\)', r'\1', x[0] + x[1]) for x in split))

        self._text = text
        self._name = self._tuple[0].lower()

    def __str__(self):
        return self._text

    def __iter__(self):
        return iter(self._tuple)

    def __getitem__(self, index):
        return self._tuple[index]

    def __len__(self):
        return len(self._tuple)

    def name(self):
        return self._name
    
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

    def __init__(self):
        self.xbmc = xbmcnp.XBMCControl(settings.XBMC_JSONRPC_URL)
        self.delimiter = '\n'
        self.command_list = []
        self.command_list_ok = True
        self.command_list_started = False
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
            self.sendLine("{}: {}".format(i[0], i[1]))

    def _process_command_list(self):
        try:
            for i, command in enumerate(self.command_list):
                logging.debug('command {} of {}: {}'.format(
                    i, len(self.command_list), str(command)))

                #for nice error messages:
                self.command_list_position = i
                self.current_command = command.name()

                if command.name() not in self.SUPPORTED_COMMANDS:
                    self.current_command = ''
                    raise MPDError(self, MPDError.ACK_ERROR_UNKNOWN,
                        '"unknown command "{}"'.format(command.name()))

                #actually handle the command
                getattr(self, command.name())(command)

                if self.command_list_ok:
                    self.sendLine('list_OK')
        except MPDError as e:
            logging.error(error.text)
            self.sendLine(str(error))
        except Exception as e:
            logging.critical('Caught an exception!', exc_info=True)
            self.sendLine(str(MPDError(
                self, MPDError.ACK_ERROR_SYSTEM, 'Internal server error, sorry.')))
        else:
            logging.debug('OK')
            self.sendLine('OK')

    def connectionMade(self):
        """
        Connection established.
        """
        self.sendLine('OK MPD 0.16.0')
    
    def lineReceived(self, data):
        """
        Receives data and takes the specified actions.
        """

        command = Command(data)

        if command.name() == 'command_list_begin':
            logging.debug('command list started')
            self.command_list = []
            self.command_list_started = True
            self.command_list_ok = False
        elif command.name() == 'command_list_ok_begin':
            logging.debug('command list started')
            self.command_list = []
            self.command_list_started = True
            self.command_list_ok = True
        elif command.name() == 'command_list_end':
            logging.debug('command list ended')
            self._process_command_list()
            self.command_list_started = False
            self.command_list_ok = False
        elif self.command_list_started:
            self.command_list.append(line)
        else:
            self.command_list = [command]
            self._process_command_list()

    def playlistinfo(self, pos=None):
        """
        Gathers informations about the current playlist.

        Uses _send_lists() to push data to the client
        """
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

    def status(self):
        """
        Player status from xbmc.

        Uses _send_lists() to push data to the client
        """
        status = self.xbmc.get_status()

        self._send_lists(
            itertools.chain([[x, status[x]] for x in status.keys()],  
            [['volume', self.xbmc.get_volume()],
            ['consume', 0],
            ['playlist', self.playlist_id],
            ['playlistlength', self.xbmc.get_playlist_length()]]))

    def stats(self):
        """
        Fetches library statistics from xbmc.

        Uses _send_lists() to push data to the client
        """
        stats = self.xbmc.get_library_stats()
        self._send_lists([[x, stats[x]] for x in stats.keys()])
        

    def tagtypes(self):
        """
        Sends a list of supported tagtypes.

        Uses _send_lists() to push data to the client
        """
        tags = ['Artist', 'Album', 'Title', 'Track', 'Name', 'Genre', 'Date']
        templist = []
        for tag in tags:
            templist.append(['tagtype', tag])
        self._send_lists(templist)

    def commands(self):
        """
        Sends a list of supported commands.

        Uses _send_lists() to push data to the client
        """
        templist = []
        for i in self.supported_commands:
            templist.append(["command", i])
        self._send_lists(templist)

    def outputs(self):
        """
        Sends a list of configured outputs.

        Uses _send_lists() to push data to the client
        """
        templist = [['outputid', 0],
                    ['outputname', 'default detected output'],
                    ['outputenabled', 1]]
        self._send_lists(templist)
        

    def notcommands(self):
        """
        Sends a list of unsupported commands.
        
        Uses _send_lists() to push data to the client
        """
        unsupported = set(self.all_commands) ^ set(self.supported_commands)
        templist = []
        for i in unsupported:
            templist.append(['command', i])
        self._send_lists(templist)

    def set_vol(self, volume):
        """
        Sets the volume.
        """
        self.xbmc.set_volume(volume)
        self._send()

    def delete_id(self, song_id):
        """
        Deletes a song by it's specified id.
        """
        self.xbmc.remove_from_playlist(song_id)
        self.playlist_id += 1
        self._send()

    def add(self, path):
        """
        Adds a specified path to the playlist.
        """
        self.xbmc.add_to_playlist(self.musicpath + path)
        self.playlist_id += 1
        self._send()

    def next(self):
        """
        Skip to the next song in the playlist.
        """
        self.xbmc.next()
        self._send()

    def previous(self):
        """
        Return to the previous song in the playlist.
        """
        self.xbmc.prev()
        self._send()

    def stop(self):
        """
        Stop playing.
        """
        self.xbmc.stop()
        self._send()

    def seek(self, song_id, seconds):
        status = self.xbmc.get_status()

        if status == None or status['PlaylistPosition'] != song_id:
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
                playlistlist.append(['file', song['file'].replace(settings.MUSICPATH, '')])
                playlistlist.append(['Time', song['duration']])
                playlistlist.append(['Artist', song['artist']])
                playlistlist.append(['Title', song['title']])
                playlistlist.append(['Album', song['album']])
                playlistlist.append(['Track', song['track']])
                playlistlist.append(['Date', song['year']])     
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

    def currentsong(self):
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
        status = self.xbmc.get_current_song()
        if status != None:
            self._send_lists([['file', status['Player.Filenameandpath'].replace(settings.MUSICPATH, '')],
                            ['Time', status['duration']],
                            ['Artist', status['MusicPlayer.Artist']],
                            ['Title', status['MusicPlayer.Title']],
                            ['Album', status['MusicPlayer.Album']],
                            ['Track', status['MusicPlayer.TrackNumber']],
                            ['Genre', status['MusicPlayer.Genre']],
                            ['Pos', status['MusicPlayer.PlaylistPosition']],
                            ['Id', status['MusicPlayer.PlaylistPosition']]])
        else:
            self._send('')
    
    def lsinfo(self, path=''):
        """
        Returns informations about the specified path.

        Uses _send_lists() to push data to the client
        """
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
    factory = twisted.internet.protocol.ServerFactory()
    factory.protocol = MPD
    twisted.internet.reactor.listenTCP(settings.MPD_PORT, factory)
    twisted.internet.reactor.run()
