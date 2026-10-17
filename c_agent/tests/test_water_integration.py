"""Water integration regression checks: real catalogue selection and state refresh."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from c_agent.agent import dispatch_live
from c_agent.water import resolve_water_catalogue_path, nearest_water_source, _cached_water_index
from contracts.validate import ROOT

class WaterIntegrationTests(unittest.TestCase):
    def test_real_catalogue_selection_and_no_mock_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'role_a_real/regional_40'
            folder.mkdir(parents=True)
            self.assertIsNone(resolve_water_catalogue_path(None,folder))
            shared=folder.parent/'water_sources.geojson';shared.write_text('{}')
            self.assertEqual(resolve_water_catalogue_path(None,folder),shared)
            local=folder/'water_sources.json';local.write_text('[]')
            self.assertEqual(resolve_water_catalogue_path(None,folder),local)
            with self.assertRaises(ValueError):resolve_water_catalogue_path(folder/'missing.json',folder)

    def test_spatial_index_cached_and_missing_dependencies_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'water.geojson';path.write_text('{}')
            _cached_water_index.cache_clear()
            with patch('c_agent.water._WATER_INDEX_AVAILABLE',True),patch('c_agent.water.WaterIndex') as index:
                index.return_value.nearest.return_value={'water_source':None}
                nearest_water_source({'lat':-2.35,'lon':114.05},path,15)
                nearest_water_source({'lat':-2.35,'lon':114.05},path,10)
                self.assertEqual(index.call_count,1)
            _cached_water_index.cache_clear()
            with patch('c_agent.water._WATER_INDEX_AVAILABLE',False):
                with self.assertRaisesRegex(ValueError,'requires'):nearest_water_source({'lat':0,'lon':0},path,15)

    def test_water_settings_refresh_old_incidents_but_stable_rerun_dedupes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            for name in ['features.json','risk.json','cells.geojson']:
                shutil.copy(ROOT/'contracts/examples'/name,folder/name)
            kwargs={'state_path':folder/'state.json','log_path':folder/'notifications.log'}
            first=dispatch_live(folder,folder/'dispatch.json',**kwargs)
            self.assertTrue(all(row['water_source'] is None for row in first))
            (folder/'water_sources.json').write_text(json.dumps([{'lat':-2.35,'lon':114.05,'kind':'canal'}]))
            updated=dispatch_live(folder,folder/'dispatch.json',**kwargs)
            self.assertNotEqual(first[0]['dispatch_id'],updated[0]['dispatch_id'])
            self.assertTrue(any(row['water_source'] for row in updated))
            log=(folder/'notifications.log').read_text()
            again=dispatch_live(folder,folder/'dispatch.json',**kwargs)
            self.assertEqual(updated,again)
            self.assertEqual(log,(folder/'notifications.log').read_text())
            changed=dispatch_live(folder,folder/'dispatch.json',max_water_km=1,**kwargs)
            self.assertNotEqual(changed[0]['dispatch_id'],again[0]['dispatch_id'])
