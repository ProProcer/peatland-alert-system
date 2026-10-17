"""Regression checks for the human-requested high/critical dispatch policy."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from c_agent.policy import decide
from c_agent.state_store import StateStore
from c_agent.tests.test_policy import _feature, _risk
from contracts.validate import validate_payload

class ImmediateDispatchTests(unittest.TestCase):
    def test_high_dispatches_with_null_stable_or_falling_moisture(self):
        for delta in [None,0,.02,-.02]:
            with self.subTest(delta=delta), tempfile.TemporaryDirectory() as temp:
                cell='-2.35_114.05'
                output,created=decide([_feature(cell,sm_delta=delta)],[_risk(cell,48,.7,'HIGH')],StateStore(Path(temp)/'state.json'))
                validate_payload('dispatch',output)
                self.assertEqual(len(created),1)
                self.assertEqual(output[0]['action'],'DISPATCH')
                self.assertEqual(len(output[0]['audiences']),5)
                self.assertIn('high-risk',output[0]['messages']['leadership']['en'])
                self.assertNotIn('critical',output[0]['messages']['leadership']['en'])

    def test_old_policy_state_replaced_then_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            state=StateStore(Path(temp)/'state.json')
            cell='-2.35_114.05'
            features=[_feature(cell,sm_delta=None)]
            risks=[_risk(cell,48,.7,'HIGH')]
            when=datetime(2026,10,17,9,5,tzinfo=timezone.utc)
            old,_=decide(features,risks,state,now=when)
            del state.get(cell)['policy_version']
            migrated,created=decide(features,risks,state,now=when)
            self.assertNotEqual(old[0]['dispatch_id'],migrated[0]['dispatch_id'])
            self.assertEqual(len(created),1)
            reused,created=decide(features,risks,state,now=when)
            self.assertEqual(reused,migrated)
            self.assertFalse(created)

    def test_severity_fall_and_quiet_levels(self):
        with tempfile.TemporaryDirectory() as temp:
            cell='-2.35_114.05'
            features=[_feature(cell,sm_delta=None)]
            state=StateStore(Path(temp)/'state.json')
            for level,score in [('CRITICAL',.9),('HIGH',.7),('MODERATE',.5),('LOW',.2)]:
                output,_=decide(features,[_risk(cell,48,score,level)],state)
                self.assertEqual(len(output),1 if level in ['CRITICAL','HIGH'] else 0)
                if output:
                    self.assertEqual(output[0]['action'],'DISPATCH')
                    self.assertEqual(output[0]['priority'],1 if level=='CRITICAL' else 2)
