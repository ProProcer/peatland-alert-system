"""Check historical analytics aggregation and source-derived exports."""
import json
from pathlib import Path
import unittest
from d_frontend.analytics_data import FIELDS, ROOT, aggregate


class HistoricalAnalyticsTests(unittest.TestCase):
    def test_partial_days_and_missing_values(self):
        import pandas as pd
        rows=[]
        for hour in range(24):
            row={key:1.0 for key,*_ in FIELDS}
            row['ts']=f'2026-10-01T{hour:02d}:00:00Z'
            rows.append(row)
        rows[-1]['rain_7d_mm']=None
        result=aggregate(pd.DataFrame(rows))[0]
        index={key:i for i,(key,*_) in enumerate(FIELDS)}
        self.assertEqual(result['values'][index['precip_mm']],24)
        self.assertEqual(result['values'][index['temp_c']],1)
        self.assertIsNone(result['values'][index['rain_7d_mm']])
        result=aggregate(pd.DataFrame(rows[:-1]))[0]
        self.assertIsNone(result['values'][index['precip_mm']])
        self.assertEqual(result['hours'],23)
        rows[0]['wind_dir_deg']=359
        rows[1]['wind_dir_deg']=1
        circular=aggregate(pd.DataFrame(rows[:2]))[0]['values'][index['wind_dir_deg']]
        self.assertLess(min(abs(circular),abs(360-circular)),.0001)
        rows[1]['ts']=rows[0]['ts']
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            aggregate(pd.DataFrame(rows))

    def test_all_40_exported_histories(self):
        root=ROOT/'d_frontend/assets/historical'
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['points']),40)
        self.assertEqual(len({p['cell_id'] for p in manifest['points']}),40)
        self.assertEqual(len({p['province'] for p in manifest['points']}),5)
        self.assertEqual(sum(p['hours'] for p in manifest['points']),656640)
        self.assertFalse(any('target' in field['key'] or 'risk' in field['key'] for field in manifest['fields']))
        for point in manifest['points']:
            data=json.loads((root/point['file']).read_text(encoding='utf-8'))
            self.assertEqual(data['cell_id'],point['cell_id'])
            self.assertEqual(sum(row['hours'] for row in data['rows']),point['hours'])
            self.assertEqual(data['rows'][0]['date'],point['start'])
            self.assertEqual(data['rows'][-1]['date'],point['end'])
            self.assertEqual(len(data['rows']),point['days'])
            for row in data['rows']:
                self.assertEqual(len(row['values']),len(FIELDS))
                self.assertEqual(len(row['valid']),len(FIELDS))
                self.assertTrue(all(0<=n<=row['hours']<=24 for n in row['valid']))
