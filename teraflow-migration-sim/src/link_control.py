"""Gate modeled contacts without closing BMv2's shared packet capture ports."""


def set_link_availability(link, available, delay_ms=0.0):
    # Administratively lowering one interface stops BMv2's shared pcap reader
    # on this backend, including unrelated ports. Drop egress on both ends
    # instead; no frame can cross a closed contact and capture stays alive.
    # The propagation delay is applied on egress at both ends, so each direction pays it once.
    delay = ['delay', f'{delay_ms:.2f}ms'] if delay_ms > 0 else []
    for interface in (link.intf1, link.intf2):
        _, error, status = interface.node.pexec([
            'tc', 'qdisc', 'replace', 'dev', interface.name,
            'root', 'netem', *delay, 'loss', '0%' if available else '100%'])
        if status:
            raise RuntimeError('Cannot configure contact on '+interface.name+': '+error)
