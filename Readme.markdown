# About
XBMC JSON RPC client on one side, MPD server on the other.
Based on mots/xbmcpd, but it begins to look as a complete rewrite.

# Arguments
  -h, --help             show this help message and exit  
  --xbmc-host XBMC_HOST  address of the xbmc machine (default: localhost)
  --xbmc-port XBMC_PORT  port of the JSON RPC interface (default: 9090)
  --port PORT, -p PORT   port for the MPD server (default: 6000)  
  --musicpath MUSICPATH  root of the music database on the XBMC machine  
  --pathsep PATHSEP      path separator on the xbmc machine (default: '/')  
  --verbose              enable debugging outputs

Arguments may be turned into configuration files using '@' prefix. See the
[argparse docs](http://docs.python.org/library/argparse.html#fromfile-prefix-chars)
and arg_example.txt in the project directory.
