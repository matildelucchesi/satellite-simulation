import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.automatic_start import select_start, SelectionRejected
from src.planner import ScenarioRejected
from src.jobs import JobManager


class AutomaticStartTests(unittest.TestCase):
    def planner(self):
        return SimpleNamespace(orbit=SimpleNamespace(ids=[2,1],duration=4),
            index=SimpleNamespace(period=lambda sid,tick:(0,100)),
            publish=Mock(),check=Mock(),rejections={})

    def plan(self,p):
        tick=p['start_orbital_s'];host=p['initial_satellite_id']
        return {'start_s':tick,'initial_satellite_id':host,'migrations':[
            {'sat_a':host,'sat_b':3,'trigger_s':tick,'estimated_operation_s':0.1,
             'deadline_s':100,'recovery_reserve_s':0.1,'contact_end_s':50+tick}]}

    def test_complete_search_uses_margin_then_earliest_time_then_lowest_norad(self):
        p=self.planner()
        with patch('src.continuous_comparison.shared_plan',side_effect=lambda _,args:self.plan(args)):
            evidence,plans=select_start(p,{'rate_bps':1000000000})
        self.assertTrue(evidence['exhaustive'])
        self.assertEqual(evidence['examined_candidates'],8)
        self.assertEqual(evidence['selected']['start_orbital_s'],0)
        self.assertEqual(evidence['selected']['initial_satellite_id'],1)

    def test_all_rates_must_accept_the_same_start(self):
        def candidate(_,args):
            if args['rate_bps']==100000000 and args['initial_satellite_id']==1:
                raise ScenarioRejected('rate constraint')
            return self.plan(args)
        with patch('src.continuous_comparison.shared_plan',side_effect=candidate):
            evidence,plans=select_start(self.planner(),{'rate_bps':1000000000},[100000000,1000000000])
        self.assertEqual(evidence['selected']['initial_satellite_id'],2)
        self.assertEqual(len(plans),2)

    def test_budget_without_candidate_is_incomplete_not_impossible(self):
        with self.assertRaises(SelectionRejected) as raised:
            select_start(self.planner(),{'rate_bps':1000000000},budget_s=1,
                         clock=Mock(side_effect=[0,0,0,2,2,2,2,2]))
        self.assertFalse(raised.exception.evidence['exhaustive'])

    def test_exhaustive_rejection_and_no_clock_started(self):
        with patch('src.continuous_comparison.shared_plan',side_effect=ScenarioRejected('no sequence')):
            with self.assertRaises(SelectionRejected) as raised:
                select_start(self.planner(),{'rate_bps':1000000000})
        self.assertTrue(raised.exception.evidence['exhaustive'])

    def test_partial_search_retains_a_verified_candidate(self):
        elapsed=[0]
        def candidate(_,args):
            elapsed[0]=2
            return self.plan(args)
        with patch('src.continuous_comparison.shared_plan',side_effect=candidate):
            evidence,plans=select_start(self.planner(),{'rate_bps':1000000000},
                budget_s=1,clock=lambda:elapsed[0])
        self.assertFalse(evidence['exhaustive'])
        self.assertIsNotNone(evidence['selected'])

    def test_more_margin_beats_earlier_start(self):
        p=self.planner();p.orbit.duration=20
        def candidate(_,args):
            plan=self.plan(args)
            plan['migrations'][0]['contact_end_s']=args['start_orbital_s']+(5 if args['start_orbital_s']==2 else 1)
            return plan
        with patch('src.continuous_comparison.shared_plan',side_effect=candidate):
            evidence,_=select_start(p,{'rate_bps':1000000000})
        self.assertEqual(evidence['selected']['start_orbital_s'],2)

    def test_cancellation_is_not_reported_as_timeout(self):
        p=self.planner();p.check.side_effect=InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):select_start(p,{'rate_bps':1000000000})

    def test_public_api_rejects_manual_coordinates_even_null(self):
        manager=object.__new__(JobManager)
        for key in ('initial_satellite_id','start_orbital_s'):
            with self.assertRaisesRegex(ValueError,'automatica'):
                manager.validate('compare_continuous',{key:None})

    def test_service_window_tracks_multihop_connectivity_and_exact_boundaries(self):
        from src.planner import OrbitIndex
        orbit=SimpleNamespace(ids=[53848,53913,7],duration=30,operational=lambda sid,tick:True)
        index=OrbitIndex(orbit,[{'sat_a':53848,'sat_b':7,'start_s':0,'end_s':30},
            {'sat_a':7,'sat_b':53913,'start_s':5,'end_s':20}])
        self.assertEqual(index.service_periods(),[(5,20)])
        self.assertEqual(index.service_contact_end(4),4)
        self.assertEqual(index.service_contact_end(5),20)
        self.assertEqual(index.service_contact_end(20),20)

    def test_controller_contact_does_not_substitute_for_service_path(self):
        from src.continuous_comparison import SharedPlanner
        shared=object.__new__(SharedPlanner);shared.check=Mock();shared.rejections={}
        shared.index=SimpleNamespace(service_contact_end=lambda tick:20)
        with patch('src.planner.Planner.ranked',return_value=(['candidate'],[])) as rank:
            self.assertEqual(shared.ranked(7,15,10,30)[0],[])
            rank.assert_not_called()
            self.assertEqual(shared.ranked(7,5,10,30)[0],['candidate'])
