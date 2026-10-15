"""Operational entrypoints for the VPA/market-data jobs (SP-379).

Making ``vpa/scripts`` a package lets the grow-forward maintenance job run as a
module (``python -m vpa.scripts.grow_forward_intraday``) on the Pi, alongside the
shell/Rundeck entrypoints that invoke it.
"""
