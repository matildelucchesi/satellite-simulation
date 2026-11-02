import json
import unittest
from pathlib import Path
import numpy as np
from src.constellation import expanded_selection,contact_windows
from src.orbit import Orbit
from tools.select_constellation import parse_tle

ROOT=Path(__file__).parents[1]


class ConstellationExpansionTests(unittest.TestCase):
    def test_balanced_expansion_retains_all_42_real_satellites(self):
        original=ROOT/'artifacts/constellation-profiles/real-450-580/original/config/selected_constellation.json'
        original=json.loads(original.read_text())
        candidates=parse_tle(ROOT/'data/starlink_2026-10-01.tle')
        first=expanded_selection(original,candidates)
        balanced=expanded_selection(first,candidates,(28,36))
        self.assertEqual(len(balanced['satellites']),64)
        self.assertEqual(balanced['metadata']['selected_plane_satellite_counts'],[28,36])
        self.assertTrue({r['norad_id'] for r in first['satellites']}.issubset({r['norad_id'] for r in balanced['satellites']}))
        self.assertTrue(all('orbital_phase_rad_at_reference' in row for row in balanced['satellites']))

    def test_real_expansion_preserves_original_objects_and_pinned_groups(self):
        original=ROOT/'artifacts/constellation-profiles/real-450-580/original/config/selected_constellation.json'
        if not original.exists():original=ROOT/'config/selected_constellation.json'
        original=json.loads(original.read_text())
        result=expanded_selection(original,parse_tle(ROOT/'data/starlink_2026-10-01.tle'))
        self.assertEqual(len(result['satellites']),42)
        self.assertEqual(result['metadata']['selected_plane_satellite_counts'],[6,36])
        self.assertTrue({r['norad_id'] for r in original['satellites']}.issubset({r['norad_id'] for r in result['satellites']}))
        self.assertTrue(all(450<=row['screening_altitude_km']<=580 for row in result['satellites']))
        self.assertFalse(result['metadata']['expansion']['synthetic_satellites'])
        self.assertLess(max(row['tle_age_hours_at_reference'] for row in result['satellites']),24)

    def test_vectorized_windows_match_geometry_at_every_sample(self):
        orbit=object.__new__(Orbit);orbit.ids=[1,2,3];orbit.duration=4
        orbit.radius=6378.137;orbit.max_range=1500
        orbit.positions=np.array([[[7000,0,0],[7000,1000 if tick<2 else 2000,0],[7000,1100,0]] for tick in range(4)],dtype=float)
        result=contact_windows(orbit,2)
        for tick in range(4):
            graph=orbit.graph(tick)
            indexed={(row['sat_a'],row['sat_b']) for row in result['windows'] if row['start_s']<=tick<row['end_s']}
            self.assertEqual(indexed,{(a,b) for a in graph for b in graph[a] if a<b})
        self.assertTrue(all(row['alignment_fits']==(row['duration_s']>=2) for row in result['windows']))
