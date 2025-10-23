"""
Unit tests for skyCatalogs_creator API comparing created files to
standard.
"""

import unittest
import os
# from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from utilities.utilities import compare, write_selected


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

        # Find the newly-generated files
        new_dir = os.getenv('CI_DATA')
        pixel = os.getenv('TRILEGAL_PIXEL')

        # Find dir for standard files
        standard_dir = os.path.join(new_dir, '..', 'ci_sample')

        main_name = f'trilegal_{pixel}.parquet'
        flux_name = f'trilegal_flux_{pixel}.parquet'

        standard_main = os.path.join(standard_dir, main_name)
        standard_flux = os.path.join(standard_dir, flux_name)

        # sparsify
        ixes = self.extracted_indices(standard_main)
        sparse_main = os.path.join(new_dir, 'sparse_' + main_name)
        write_selected(standard_main, sparse_main, ixes)
        sparse_flux = os.path.join(new_dir, 'sparse_' + flux_name)
        write_selected(standard_flux, sparse_flux, ixes)

        # compare
        compare(standard_main, sparse_main)
        compare(standard_flux, sparse_flux, cat_type='flux')


if __name__ == '__main__':
    unittest.main()
