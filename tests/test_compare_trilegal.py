"""
Unit tests for skyCatalogs_creator API comparing created files to
standard.
"""

import unittest
import os
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from utilities.utilities import compare, write_selected

PACKAGE_DIR = os.path.dirname(os.path.abspath(str(Path(__file__).parent)))
CI_DATA = os.path.join(PACKAGE_DIR, 'skycatalogs_creator', 'data', 'ci')
CI_SAMPLE = os.path.join(PACKAGE_DIR, 'skycatalogs_creator', 'data',
                         'ci_sample')


class TrilegalCompare(unittest.TestCase):

    def setUp(self):
        '''
        Nothing to do
        '''
        pass

    def tearDown(self):
        pass                  # nothing to do

    def extracted_indices(self, file):
        '''
        Parameters
        ----------
        file    (string)  path to a parquet file

        Returns
        -------
        List of int.   Indices of rows in file w.r.t. original catalog
                       file was extracted from
        '''
        pq_file = pq.ParquetFile(file)
        ids = np.array(pq_file.read_row_group(0, columns=['id'])['id'])
        ixes = [int(id.split('_')[-1:][0]) for id in ids]

        return ixes

    def testcompare_trilegal(self):
        '''
        Compare newly generated main and flux files to the standard ones
        Stored under data/ci_sample.   But first have to sparsify new
        ones so rows match those in the standard ones.
        '''

        pixel = os.getenv('TRILEGAL_PIXEL', default='9556')

        # Find dir for standard files
        standard_dir = CI_SAMPLE

        main_name = f'trilegal_{pixel}.parquet'
        flux_name = f'trilegal_flux_{pixel}.parquet'

        standard_main = os.path.join(standard_dir, main_name)
        standard_flux = os.path.join(standard_dir, flux_name)

        new_main = os.path.join(CI_DATA, main_name)
        new_flux = os.path.join(CI_DATA, flux_name)

        # sparsify
        ixes = self.extracted_indices(standard_main)
        sparse_main = os.path.join(CI_DATA, 'sparse_' + main_name)
        write_selected(new_main, sparse_main, ixes, debug=True)
        sparse_flux = os.path.join(CI_DATA, 'sparse_' + flux_name)
        write_selected(new_flux, sparse_flux, ixes, debug=True)

        # compare
        compare(standard_main, sparse_main, debug=True)
        compare(standard_flux, sparse_flux, cat_type='flux', debug=True)


if __name__ == '__main__':
    unittest.main()
