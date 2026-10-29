"""Exact plan-profile admission checks; no files, processes or originals needed."""
import unittest
import build_bundle as builder


class ProfileTests(unittest.TestCase):
    def plan(self, profile=None, remote=False):
        paths = builder.NETWORK_CORE | builder.NETWORK_HELPERS if profile == 'network-only' else set(builder.BASE) | builder.HELPERS
        value = {'artifacts': [{'path': p} for p in sorted(paths | (builder.OPTIONAL if remote else set()))]}
        if profile is not None:
            value['profile'] = profile
        return value

    def test_exact_six_seven_eight_nine(self):
        for profile in (None, 'network-only'):
            for remote in (False, True):
                plan = self.plan(profile, remote)
                self.assertEqual(builder.profile_paths(plan), profile)
                self.assertEqual(len(plan['artifacts']), (6 if profile else 8) + remote)

    def test_every_required_network_path(self):
        for path in builder.NETWORK_CORE | builder.NETWORK_HELPERS:
            plan = self.plan('network-only')
            plan['artifacts'] = [a for a in plan['artifacts'] if a['path'] != path]
            with self.subTest(path=path), self.assertRaises(ValueError):
                builder.profile_paths(plan)

    def test_mixed_optional_paths(self):
        for path in (set(builder.BASE) | builder.HELPERS) - (builder.NETWORK_CORE | builder.NETWORK_HELPERS):
            plan = self.plan('network-only');plan['artifacts'].append({'path': path})
            with self.subTest(path=path), self.assertRaises(ValueError):
                builder.profile_paths(plan)

    def test_explicit_marker_and_correct_helper(self):
        for marker in (None, 'unknown', 'NETWORK-ONLY'):
            plan = self.plan('network-only')
            if marker is None:
                del plan['profile']
            else:
                plan['profile'] = marker
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                builder.profile_paths(plan)
        plan=self.plan();plan['profile']='network-only'
        with self.assertRaises(ValueError):builder.profile_paths(plan)

    def test_duplicate_unknown_and_null_profile(self):
        for extra in ('NebulaNetworkBridge.dll', 'Other.dll'):
            plan=self.plan('network-only');plan['artifacts'].append({'path':extra})
            with self.assertRaises(ValueError):builder.profile_paths(plan)
        plan=self.plan();plan['profile']=None
        with self.assertRaises(ValueError):builder.profile_paths(plan)

    def test_optional_plan_transport_matches_derived_artifacts(self):
        for remote in (False, True):
            plan=self.plan('network-only', remote);plan['transport']='remote' if remote else 'direct'
            self.assertEqual(builder.profile_paths(plan),'network-only')
            plan['transport']='direct' if remote else 'remote'
            with self.assertRaises(ValueError):builder.profile_paths(plan)
        plan=self.plan();plan['transport']='direct'
        with self.assertRaises(ValueError):builder.profile_paths(plan)


if __name__ == '__main__':
    unittest.main()
