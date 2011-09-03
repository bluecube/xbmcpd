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

import logging
import twisted.internet.reactor
import twisted.internet.protocol
import twisted.protocols.basic
import argparse

import mpd
import xbmc

arg_parser = argparse.ArgumentParser(
    description="Controlling XBMC from MPD clients.",
    fromfile_prefix_chars="@")

arg_parser.add_argument('--url', default='http://localhost/jsonrpc',
    help="URL of the JSONRPC interface (default: %(default)s)")
arg_parser.add_argument('--port', '-p', default=6000, type=int,
    help="port for the MPD server (default: %(default)s)")
arg_parser.add_argument('--musicpath', required=True,
    help="root of the music database on the XBMC machine")
arg_parser.add_argument('--pathsep', default='/',
    help="path separator on the xbmc machine (default: '%(default)s')")
arg_parser.add_argument('--verbose',
    action='store_const', const=logging.DEBUG, default=logging.INFO,
    help="enable debugging outputs")
arguments = arg_parser.parse_args()

logging.basicConfig(level=arguments.verbose, format=u'%(asctime)s %(message)s',
    datefmt=u'%x %X')
logging.info("XBMCpd starting")

xbmc = xbmc.XBMCControl(arguments.url, arguments.pathsep)
mpd.MPD.xbmc = xbmc
mpd.MPD.musicpath = arguments.musicpath.rstrip(xbmc.path_sep)

logging.debug("downloading library...")

factory = twisted.internet.protocol.ServerFactory()
factory.protocol = mpd.MPD
twisted.internet.reactor.listenTCP(arguments.port, factory)

logging.info('starting MPD server at port {}'.format(arguments.port))

twisted.internet.reactor.run()
