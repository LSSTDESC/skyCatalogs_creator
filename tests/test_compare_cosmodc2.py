"""
Unit tests for skyCatalogs_creator API comparing created files to
standard.
This one is for cosmodc2 files
"""

import unittest
import os
from pathlib import Path
from skycatalogs_creator.main_catalog_creator import MainCatalogCreator
from skycatalogs_creator.flux_catalog_creator import FluxCatalogCreator

from utilities.utilities import compare    # , write_selected

PACKAGE_DIR = os.path.dirname(os.path.abspath(str(Path(__file__).parent)))
NEW_DATA = os.path.join(PACKAGE_DIR, 'skycatalogs_creator', 'data', 'ci')
CI_SAMPLE = os.path.join(PACKAGE_DIR, 'skycatalogs_creator', 'data',
                         'ci_sample')


class Cosmodc2Compare(unittest.TestCase):
    def setUp(self):
        '''
        GCRCatalogs needs some special setup but it's handled in
        main_catalog_creator, triggered by using special value
        'GCR_CI' for truth
        '''

        truth = 'GCR_CI'
        self._pixels = [9556]
        self._object_type = 'cosmodc2_galaxy'
        self._skycatalog_root = NEW_DATA
        self._main_creator = MainCatalogCreator(
            self._object_type, self._pixels,
            skycatalog_root=self._skycatalog_root,
            truth=truth)

    def tearDown(self):
        pass                  # nothing to do

    def testcompare_cosmodc2(self):
        '''
        Generate new skyCatalogs from the mini-cosmodc2 catalog.
        Then compare to standard
        '''

        # create new files
        self._main_creator.create()

        self._flux_creator = FluxCatalogCreator(
            self._object_type, self._pixels,
            skycatalog_root=self._skycatalog_root)
        self._flux_creator.create()

        # Find dir for standard files
        standard_dir = CI_SAMPLE

        pixel = self._pixels[0]
        main_name = f'galaxy_{pixel}.parquet'
        flux_name = f'galaxy_flux_{pixel}.parquet'

        standard_main = os.path.join(standard_dir, main_name)
        standard_flux = os.path.join(standard_dir, flux_name)

        new_main = os.path.join(NEW_DATA, main_name)
        new_flux = os.path.join(NEW_DATA, flux_name)

        # compare
        compare(standard_main, new_main, object_type='cosmodc2_galaxy',
                debug=True)
        compare(standard_flux, new_flux, object_type='cosmodc2_galaxy',
                cat_type='flux', debug=True)


if __name__ == '__main__':
    unittest.main()
