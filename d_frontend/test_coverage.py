"""Check that representative samples are spread out without relocating cells."""
from pathlib import Path
import unittest
import pandas as pd
from d_frontend.prepare_coverage import select_spread

ROOT = Path(__file__).resolve().parents[1]


class CoverageTests(unittest.TestCase):
    def test_spread_selection_preserves_real_grid_coordinates(self):
        cells = pd.read_parquet(ROOT / 'data/demo/role_a_real/cells.parquet')
        central = cells[(cells.province == 'Central Kalimantan') & (cells.peat_fraction >= .05)]
        selected, radius = select_spread(central)
        repeat, _ = select_spread(central.sample(frac=1, random_state=7))
        self.assertEqual(len(selected), 33)
        self.assertEqual(selected.cell_id.nunique(), 33)
        self.assertEqual(selected.cell_id.tolist(), repeat.cell_id.tolist())
        self.assertGreater(selected.lon.max() - selected.lon.min(), 4)
        self.assertGreater(selected.lat.max() - selected.lat.min(), 1.8)
        self.assertLess(radius, 40)
        original = central.set_index('cell_id')
        for row in selected.itertuples():
            self.assertEqual(row.lat, original.loc[row.cell_id, 'lat'])
            self.assertEqual(row.lon, original.loc[row.cell_id, 'lon'])
            self.assertGreaterEqual(row.peat_fraction, .05)


if __name__ == '__main__':
    unittest.main()
