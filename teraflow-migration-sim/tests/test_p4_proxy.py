"""Run in the Device container to use the pinned P4 protobuf definitions."""
import unittest
from pathlib import Path

try:
    from google.protobuf import text_format
    from p4.config.v1 import p4info_pb2
    from p4.v1 import p4runtime_pb2 as pb
    from src.p4_proxy import SwitchState, Proxy, entry_key, content
    from src.authority import Authority
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "Pinned P4 protobufs require the Device container")
class ProxyTests(unittest.TestCase):
    def setup_state(self):
        class Backend:
            device_id = 6
            def __init__(self): self.stub = self
            def require_master(self): pass
            def GetForwardingPipelineConfig(self, *args, **kwargs):
                return pb.GetForwardingPipelineConfigResponse()
            def Read(self, *args, **kwargs):
                raise AssertionError("Standby desired state must not read active hardware")
        state = SwitchState(Backend(), Authority())
        info = p4info_pb2.P4Info()
        text_format.Parse((Path(__file__).parents[1]/'deploy/p4/p4info.txt').read_text(), info)
        state.pipeline['sat-b'] = pb.ForwardingPipelineConfig(p4info=info)
        profile = next(p for p in info.action_profiles if p.preamble.name == 'FabricIngress.next.hashed_profile')
        action = next(a for a in info.actions if a.preamble.name == 'FabricIngress.next.output_hashed')
        member = pb.Entity()
        member.action_profile_member.action_profile_id = profile.preamble.id
        member.action_profile_member.member_id = 2
        member.action_profile_member.action.action_id = action.preamble.id
        for parameter in action.params:
            item = member.action_profile_member.action.params.add()
            item.param_id, item.value = parameter.id, b'\x02'
        state.validate('sat-b', member)
        state.entries['sat-b'][entry_key(member)] = member
        group = pb.Entity()
        group.action_profile_group.action_profile_id = profile.preamble.id
        group.action_profile_group.group_id = 2
        group.action_profile_group.members.add(member_id=2, weight=1)
        state.validate('sat-b', group)
        state.entries['sat-b'][entry_key(group)] = group
        return state, member, group

    def test_content_preserves_member_oneof(self):
        _, member, _ = self.setup_state()
        roundtrip = pb.Entity.FromString(content(member))
        self.assertEqual(roundtrip.WhichOneof('entity'), 'action_profile_member')

    def test_delete_member_requires_identity_without_action_parameters(self):
        state, member, _ = self.setup_state()
        member.action_profile_member.ClearField('action')
        request = pb.WriteRequest(device_id=6)
        request.updates.add(type=pb.Update.DELETE, entity=member)
        class Context:
            def abort(self, code, message): raise AssertionError(message)
        Proxy(state, 'sat-b').Write(request, Context())
        self.assertNotIn(entry_key(member), state.entries['sat-b'])

    def test_standby_profile_reads_use_staged_state(self):
        state, member, group = self.setup_state()
        request = pb.ReadRequest(device_id=6)
        request.entities.add().action_profile_member.action_profile_id = 0
        request.entities.add().action_profile_group.action_profile_id = 0
        class Context:
            def abort(self, code, message): raise AssertionError(message)
        responses = list(Proxy(state, 'sat-b').Read(request, Context()))
        self.assertEqual({entry_key(e) for response in responses for e in response.entities},
                         {entry_key(member), entry_key(group)})

    def test_group_rejects_missing_member(self):
        state, _, group = self.setup_state()
        group.action_profile_group.members[0].member_id = 999
        with self.assertRaises(ValueError): state.validate('sat-b', group)

    def test_member_and_group_in_one_batch_remain_staged(self):
        state, member, group = self.setup_state()
        state.entries['sat-b'].clear()
        request = pb.WriteRequest(device_id=6)
        request.updates.add(type=pb.Update.INSERT, entity=member)
        request.updates.add(type=pb.Update.INSERT, entity=group)
        class Context:
            def abort(self, code, message): raise AssertionError(message)
        Proxy(state, 'sat-b').Write(request, Context())
        self.assertEqual(set(state.entries['sat-b']), {entry_key(member), entry_key(group)})
