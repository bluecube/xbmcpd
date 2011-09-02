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

import time
import functools

import jsonrpc.proxy
from pprint import pprint

import settings

def timed_cache(timeout):
    def decorator(f):
        cache = {}
        
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            now = time.time()

            key = (f, tuple(args), frozenset(kwargs.items()))

            if key not in cache or cache[key][0] + timeout < now:
                cache[key] = (now, f(*args, **kwargs))
                
            return cache[key][1]

        return wrapper

    return decorator


class XBMCControl(object):
    """
    Implements a simple way to control basic XBMC library functions.
    """

    ALL_FIELDS = [
        'title',
        'artist',
        'genre',
        'year',
        'album',
        'track',
        'duration',
        'file']
    
    SONG_FIELDS = [
        'file',
        'title',
        'artist',
        'album',
        'track',
        'genre',
        'year',
        'duration']

    SUPPORTED_VERSION = 3

    PLAYLIST_TIMEOUT = 3
    LIBRARY_TIMEOUT = 3600

    def __init__(self, url, path_sep='/'):
        self.call = jsonrpc.proxy.JSONRPCProxy.from_url(url)

        self._check_version()
        self.path_sep = path_sep
        
    def _check_version(self):
        jsonrpc_version = self.call.JSONRPC.Version()['version']
        if jsonrpc_version != self.SUPPORTED_VERSION:
            raise RuntimeError(
                'Unsupported protocol version {}.'.format(jsonrpc_version))

    def get_time(self):
        """
        Return a tuple with elapsed time and duration of the current song
        or None if player is stopped.
        """
        try:
            time = self.call.AudioPlayer.GetTime()
        except jsonrpc.common.RPCError as e:
            if e.code != -32100:
                raise

            return None

        return (self._process_time(time['time']), self._process_time(time['total']))

    def _process_time(self, time):
        return 3600 * time['hours'] + 60 * time['minutes'] + time['seconds']
        
    def get_volume(self):
        """
        Get the currently set volume.

        Returns an integer.
        """
        return self.call.XBMC.GetVolume()

    def get_directory(self, path):
        """
        Get list of files, list of directories and list of playlists.
        """
        #TODO: Attempting to list a nonexistent directory causes an exception. Detect it.

        filelist = []
        dirlist = []
        pllist = []

        for f in self.call.Files.GetDirectory(
            directory=path, fields=self.ALL_FIELDS, media='music')['files']:
            if f['filetype'] == 'directory':
                if f['file'].endswith(self.path_sep):
                    dirlist.append(f)
                else:
                    pllist.append(f)
            else:
                filelist.append(f)

        return (filelist, dirlist, pllist)


    def list_playlists(self):
        return [] #TODO: Implement this when jsonrpc api supports listing playlists.

    @timed_cache(PLAYLIST_TIMEOUT)
    def get_current_playlist(self):
        """
        Get the music playlist contents.

        Returns a list filled by each file's tags
        """
        x = self.call.AudioPlaylist.GetItems(fields=self.SONG_FIELDS)
        if 'state' in x:
            self.playlist_state = x['state'] #TODO: This is ugly.
        else:
            self.playlist_state = None

        return x.get('items', [])

    def next(self):
        """
        Skip to the next song.
        """
        self.call.AudioPlayer.SkipNext()

    def prev(self):
        """
        Return to the previous song.
        """
        self.call.AudioPlayer.SkipPrevious()

    def stop(self):
        """
        Stop playing.
        """
        try:
            self.call.AudioPlayer.Stop()
        except jsonrpc.common.RPCError as e:
            if e.code != -32100:
                raise

    def set_volume(self, volume):
        """
        Set the volume.
        """
        self.call.XBMC.SetVolume(int(volume))

    @timed_cache(LIBRARY_TIMEOUT)
    def list_songs(self):
        """
        List of all songs
        """
        return self.call.AudioLibrary.GetSongs(fields=self.SONG_FIELDS)['songs']

    def seekto(self, time):
        """
        Seek to a given time in a current song.
        """
        self.call.AudioPlayer.SeekTime(time)

    def playid(self, song_id):
        """
        Play song specified by it's id.
        """
        self.call.AudioPlaylist.Play(song_id)

    def playpause(self):
        """
        Toggle play or pause, updates the playlist state.
        """
        try:
            result = self.call.AudioPlayer.PlayPause()
        except jsonrpc.common.RPCError as e:
            if e.code != -32100:
                raise

            self.call.AudioPlaylist.Play()
        else:
            self.playlist_state.update(result)

    def play(self):
        self.update_playlist_state()

        if self.playlist_state is None or self.playlist_state['paused']:
            self.playpause()

    def pause(self):
        self.update_playlist_state()
        
        if self.playlist_state is None or self.playlist_state['paused']:
            return

        self.playpause()

    def remove_from_playlist(self, pos):
        """
        Remove a song (specified by it's position inside the playlist) from
        the playlist.
        """
        self.call.AudioPlaylist.Remove(pos)
    
    def add_to_playlist(self, path):
        """
        Add the given path to the playlist.
        """
        # This is a little hack ...
        # XBMC wants to know if the item added is a file or a directory
        # so we try to add the item as a file and if this fails try adding
        # it as a directory
        try:
            self.call.AudioPlaylist.Add({'file': path})
            return
        except jsonrpc.common.RPCError as e:
            if e.code != -32602:
                raise

        self.call.AudioPlaylist.Add({'directory': path})

    def insert_into_playlist(self, path, position):
        """
        Add given path to the playlist at a position.
        """
        #The same hack as for add_to_playlist
        try:
            self.call.AudioPlaylist.Insert(position, {'file': path})
            return
        except jsonrpc.common.RPCError as e:
            if e.code != -32602:
                raise

        self.call.AudioPlaylist.Insert(position, {'directory': path})

    def clear(self):
        """
        Clear the current playlist
        """
        self.call.AudioPlaylist.Clear()

    def update_playlist_state(self):
        """
        Forces playlist state update.
        (otherwise state is updated only in get_current_playlist when
        cache times out)
        """
        try:
            self.playlist_state = self.call.AudioPlaylist.State()
        except jsonrpc.common.RPCError as e:
            if e.code != -32602:
                raise
        
            self.playlist_state = None

    def force_playlist_update(self):
        """
        Imediately download a new playlist and discard the cached version.
        To be used with playlist modifying functions.
        """
        pass
        #TODO: Write this function
