# Passive Protocol Capture Support

## Capture Baseline

The client already uses Scapy for passive DHCP capture. The new listener will
use the same packet-capture mechanism and selected interface; it will not bind
application sockets, send multicast queries, fetch advertised URLs, or perform
any other active discovery.

On Windows, live capture requires Npcap and a process account that has access
to its capture interface. That prerequisite already applies to the existing
DHCP listener. Packet visibility is limited to traffic delivered to the client
interface. On a switched network, unicast traffic between other devices is not
expected to be visible; multicast visibility can also vary with switch and
wireless multicast handling.

The initial listener will use one Scapy capture worker with a UDP port filter
for the supported protocols. If the platform cannot apply the BPF filter, it
may fall back to a Scapy packet predicate, matching the existing DHCP
listener's availability behavior.

## Protocol Decisions

| Protocol | Ports and capture | Useful passive fields | Initial decision |
| --- | --- | --- | --- |
| mDNS / DNS-SD | UDP 5353; IPv4 `224.0.0.251` and IPv6 `FF02::FB` | Host names, A/AAAA addresses, PTR service types and instances, SRV targets/ports, TXT attributes | Implement |
| LLMNR | UDP 5355; IPv4 `224.0.0.252` and IPv6 `FF02::1:3` | Query names, response names, A/AAAA addresses | Implement |
| NBNS | UDP 137 | NetBIOS names, query/response type, source address, response addresses where present | Implement |
| SSDP / UPnP | UDP 1900; multicast and unicast responses | `NT`/`ST`, `USN`, `SERVER`, `LOCATION`, cache control, source address | Implement |
| DHCPv6 | UDP 546/547 | DUID, IA addresses, FQDN/vendor options where present | Defer |
| LLDP / CDP | Ethernet frames, not UDP | Directly attached switch identity and capabilities | Defer |

## Implementation Notes

### mDNS / DNS-SD

mDNS uses DNS message encoding, so parsing can reuse a bounded DNS parser.
DNS-SD commonly provides PTR, SRV, and TXT records together with A or AAAA
records. The listener will retain only safe, useful metadata: host name,
service type, service instance, target address, port, and a size-limited map
of TXT values. It must not interpret TXT fields as trusted identity data.

### LLMNR

LLMNR is DNS-format name resolution on the local link, but it is not service
discovery. The listener will record query names and response-derived names/IPs
as separate observations. A query alone establishes only that the sender asked
for a name; it must not be presented as proof that a device owns that name.

### NBNS

NBNS name service packets need a small NetBIOS-name decoder rather than a DNS
parser. The parser will be defensive: malformed labels, compressed names, and
payloads beyond a small fixed limit are ignored. A packet source MAC is useful
only when the capture includes an Ethernet layer, so MAC remains optional.

### SSDP / UPnP

SSDP payloads are HTTP-like header blocks. The listener will recognize
`NOTIFY`, `M-SEARCH`, and response packets, then retain a bounded allowlist of
headers. `LOCATION` is recorded as an advertisement only; the listener will
not request it, because doing so would turn passive observation into active
probing. Manufacturer and model fields are not generally present in SSDP
headers and must therefore remain optional/unset until a future, explicitly
active enrichment feature exists.

### DHCPv6

DHCPv6 can reveal useful identifiers, but it does not reliably carry a MAC
address, requires an independent option parser, and is outside the current
DHCP listener's IPv4-focused data model. It remains a future protocol so that
it cannot alter or complicate the existing DHCP path.

### LLDP / CDP

These are Layer-2 control protocols. A Windows endpoint may observe
advertisements from its directly connected access switch, but not a useful
neighbourhood of other endpoint devices on a normal switched network. They are
not part of the first passive-protocol listener.

## First Implementation Scope

The first implementation will parse mDNS, LLMNR, NBNS, and SSDP packets that
are already visible on the selected client interface. It will use an in-memory,
bounded, deduplicated observation buffer and record protocol, observed time,
source IP/MAC when available, extracted identity fields, and a small
protocol-specific `raw_fields` object.

No packet causes an immediate server message. No existing ARP, daily
neighbourhood, or DHCP storage is read or modified.

## Sources

- [Scapy Windows installation and Npcap guidance](https://scapy.readthedocs.io/en/stable/installation.html)
- [Scapy sniffing and packet-capture behavior](https://scapy.readthedocs.io/en/stable/usage.html)
- [RFC 6762: Multicast DNS](https://www.rfc-editor.org/info/rfc6762/)
- [RFC 6763: DNS-Based Service Discovery](https://www.rfc-editor.org/info/rfc6763/)
- [RFC 4795: Link-Local Multicast Name Resolution](https://www.rfc-editor.org/info/rfc4795/)
- [RFC 1002: NetBIOS over TCP/UDP](https://www.rfc-editor.org/info/rfc1002/)
- [RFC 8415: DHCPv6](https://datatracker.ietf.org/doc/html/rfc8415)
