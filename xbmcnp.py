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

import jsonrpc.proxy
from pprint import pprint

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

    SUPPORTED_VERSION = 3

    def __init__(self, url):
        self.call = jsonrpc.proxy.JSONRPCProxy.from_url(url)

        self._check_version()

        #update the temporary data
        self.list_artists()

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
        
    def get_status(self):
        """
        Get status of the music player.

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
            'MusicPlayer.TrackNumber',
            'MusicPlayer.Duration',
            'MusicPlayer.BitRate',
            'MusicPlayer.SampleRate',
            'MusicPlayer.Time',
            'MusicPlayer.PlaylistPosition'])
        
        labels['paused'] = state['paused']
        
        minutes, seconds = labels['MusicPlayer.Time'].split(':')
        labels['time'] = 60 * int(minutes) + int(seconds)

        minutes, seconds = labels['MusicPlayer.Duration'].split(':')
        labels['duration'] = 60 * int(minutes) + int(seconds)

        return labels
        
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
        pass #TODO: Implement this when jsonrpc api supports listing playlists.

    def get_current_playlist(self):
        """
        Get the music playlist contents.

        Returns a list filled by each file's tags
        """
        return self.call.AudioPlaylist.GetItems(fields=self.ALL_FIELDS)['items']

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

    def list_artists(self):
        """
        Returns a list of all artists.
        """
        artists = self.call.AudioLibrary.GetArtists(fields=[])['artists']
        self.artistdict = dict(((x['label'], x['artistid']) for x in artists))
        return artists

    def list_genres(self):
        """
        Returns a list of all genres.
        """
        return self.call.AudioLibrary.GetGenres()['genres']

    def count_artist(self, artist):
        """
        Get number of songs by the specified artist and the total duration.

        Returns number of songs, total duration
        """
        response = self.call.MusicLibrary.GetSongs(
            artistid=self.artistdict[artist], fields=['duration'])

        duration = 0
        for song in response['songs']:
            duration += song['duration']

        return response['limits']['total'], duration

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
    
    def list_artist_albums(self, artist):
        """
        Get all albums by a specified artist.

        Returns a list.
        """
        return self.call.AudioLibrary.GetAlbums(artistid=artistdict[artist])['albums']

    def list_albums(self):
        """
        Get all albums inside the library.

        Returns a list
        """
        albums = self.call.AudioLibrary.GetAlbums(fields=['year'])['albums']
        self.albumdict = dict(((x['label'], x['albumid']) for x in albums))
        self.years = (x['year'] for x in albums if x['year'] != 0)
        return albums

    def list_album_date(self, album):
        """
        Get the date of the specified album.

        Returns a string
        """
        return self.call.AudioLibrary.GetAlbumDetails(
            albumid=self.albumdict[album], fields=['year'])['year']

    def add_to_playlist(self, path):
        """
        Add the given path to the playlist.
        """
        self.call.AudioPlaylist.Add({'file': path})

    def list_dates(self):
        """
        Get a list of dates for which albums are available.

        Returns a list.
        """
        return self.dates
