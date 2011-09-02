# About
XBMC JSON RPC client on one side, MPD server on the other.
Based on mots/xbmcpd, but it begins to look as a complete rewrite.

# Dependencies
Only NCMI/jsonrpc.

# Running

arguments:
  -h, --help            show this help message and exit
  --url URL             URL of the JSONRPC interface (default:
                        http://localhost/jsonrpc)
  --port PORT, -p PORT  port for the MPD server (default: 6000)
  --musicpath MUSICPATH
                        root of the music database on the XBMC machine
  --pathsep PATHSEP     path separator on the xbmc machine (default: '/')
  --verbose             enable debugging outputs

parameters may be put into configuration files. See the
(argparse docs)[http://docs.python.org/library/argparse.html#fromfile-prefix-chars]
and arg_example.txt in the project directory.

Once configured, xbmcpd.py can be run (through Python), to start the wrapper.
