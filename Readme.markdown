# About
XBMC JSON RPC client on one side, MPD server on the other.
Based on mots/xbmcpd, but it begins to look as a complete rewrite.

# Dependencies
Only NCMI/jsonrpc.

# Configuration
File settings.py contains the parameters for xbmcPD to connect to the XBMC
JSON RPC api (XBMC_JSONRPC_URL)
The port to expose the MPD API for MPD clients is configured in the same file (MPD_PORT).
Variable MUSICPATH selects the root directory where the music is stored.

# Running
Once configured, xbmcpd.py can be run (through Python), to start the wrapper.
