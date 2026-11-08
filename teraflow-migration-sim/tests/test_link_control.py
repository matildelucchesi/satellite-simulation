import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.link_control import set_link_availability


class ContactGatingTests(unittest.TestCase):
    def test_closed_contact_drops_both_directions_without_lowering_interfaces(self):
        ports=[SimpleNamespace(name=name,node=SimpleNamespace(pexec=Mock(return_value=('', '', 0))))
               for name in ('s6-eth1','s1-eth1')]
        link=SimpleNamespace(intf1=ports[0],intf2=ports[1])
        for enabled,loss in ((False,'100%'),(True,'0%')):
            set_link_availability(link,enabled)
            for port in ports:
                port.node.pexec.assert_called_with(['tc','qdisc','replace','dev',port.name,'root','netem','loss',loss])

    def test_open_link_carries_its_propagation_delay(self):
        ports=[SimpleNamespace(name=name,node=SimpleNamespace(pexec=Mock(return_value=('', '', 0))))
               for name in ('s6-eth1','s1-eth1')]
        set_link_availability(SimpleNamespace(intf1=ports[0],intf2=ports[1]),True,4.62)
        for port in ports:
            port.node.pexec.assert_called_with(['tc','qdisc','replace','dev',port.name,'root','netem','delay','4.62ms','loss','0%'])

    def test_contact_configuration_failure_is_not_silently_accepted(self):
        bad=SimpleNamespace(name='s6-eth1',node=SimpleNamespace(pexec=Mock(return_value=('', 'not permitted', 2))))
        other=Mock()
        with self.assertRaisesRegex(RuntimeError,'not permitted'):
            set_link_availability(SimpleNamespace(intf1=bad,intf2=other),False)
        other.node.pexec.assert_not_called()
