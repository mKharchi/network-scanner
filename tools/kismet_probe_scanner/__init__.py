"""Kismet Unicast Filter & Probe Scanner — standalone tool package.

Lives under tools/kismet_probe_scanner/, outside server/ and client/.
Reuses existing 802.11 parsing primitives from server_components; never
introduces a parallel parser or copies raw packet bytes.
"""
