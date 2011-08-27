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

    def __init__(self, url):
        self.call = jsonrpc.proxy.JSONRPCProxy.from_url(url)

        self._check_version()
        
    def _check_version(self):
        jsonrpc_version = self.call.JSONRPC.Version()['version']
        if jsonrpc_version != self.SUPPORTED_VERSION:
            raise RuntimeError(
                'Unsupported protocol version {}.'.format(jsonrpc_version))
    
    def get_current_song(self):
        """
        Get currently playing file.

        Returns a dictionary or None.
        """

        try:
            state = self.call.AudioPlayer.State()
        except jsonrpc.common.RPCError as e:
            if e.code == -32100:
                return None
            else:
                raise

        labels = self.call.System.GetInfoLabels([
            'MusicPlayer.Title',
            'MusicPlayer.Artist',
            'MusicPlayer.Album',
            'MusicPlayer.TrackNumber',
            'MusicPlayer.Genre',
            'MusicPlayer.Duration',
            'MusicPlayer.PlaylistPosition',
            'Player.Filenameandpath'])

        minutes, seconds = labels['MusicPlayer.Duration'].split(':')
        labels['duration'] = 60 * int(minutes) + int(seconds)

        return labels

    def get_library_stats(self):
        ret = {}
        ret["artists"] = self.call.AudioLibrary.GetSongs(
            limits={'start':0, 'end':1})['limits']['total']
        ret["albums"] = self.call.AudioLibrary.GetAlbums(
            limits={'start':0, 'end':1})['limits']['total']

        songs = self.call.AudioLibrary.GetSongs(fields=["duration"])
        
        ret["songs"] = songs['limits']['total']

        ret["db_playtime"] = sum([x["duration"] for x in songs["songs"]])

        return ret

    def get_status(self):
        ret = {}

        try:
            state = self.call.AudioPlaylist.State()
        except jsonrpc.common.RPCError as e:
            if e.code != -32100:
                raise

            ret["single"] = 0
            ret["repeat"] = 0
            ret["random"] = 0
            ret["state"] = "stop"

            return ret

        if state["repeat"] == "all":
            ret["repeat"] = 1
            ret["single"] = 0
        elif state["repeat"] == "one":
            ret["repeat"] = 1
            ret["single"] = 1
        else:
            ret["repeat"] = 0

        if state["shuffled"]:
            ret["random"] = 1
        else:
            ret["random"] = 0
        
        if state["paused"]:
            ret["state"] = "paused"
        elif state["playing"]:
            ret["state"] = "play"
        else:
            ret["state"] = "stop"
            return ret

        ret["song"] = state['current']

        time = self.call.AudioPlayer.GetTime()
        elapsed = self._process_time(time['time'])
        duration = self._process_time(time['total'])

        ret["time"] = "{}:{}".format(elapsed, duration)

        return ret

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
        Get directory informations.

        Returns a list of subdirectories and musicfiles
        """
        return self.call.Files.GetDirectory(directory=path,
            fields=self.ALL_FIELDS,
            media='music')['files']
        #TODO: Attempting to list a nonexistent directory causes an exception. Detect it.

    def list_playlists(self):
        return [] #TODO: Implement this when jsonrpc api supports listing playlists.

    @timed_cache(PLAYLIST_TIMEOUT)
    def get_current_playlist(self):
        """
        Get the music playlist contents.

        Returns a list filled by each file's tags
        """
        return self.call.AudioPlaylist.GetItems(fields=self.SONG_FIELDS)['items']

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

    def get_playlist_length(self):
        """
        Get the playlist length.
        """
        return self.call.AudioPlaylist.GetItems(
            fields=[], limits={'start':0, 'end':1})['limits']['total']

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
        Toggle play or pause.
        """
        try:
            self.call.AudioPlayer.PlayPause()
        except jsonrpc.common.RPCError as e:
            if e.code != -32100:
                raise

            self.call.AudioPlaylist.Play(0)

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
        # TODO: This is a little hack ...
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

    def clear(self):
        """
        Clear the current playlist
        """
        self.call.AudioPlaylist.Clear()
