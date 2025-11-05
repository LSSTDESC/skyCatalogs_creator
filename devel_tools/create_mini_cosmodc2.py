import os
import shutil
import argparse
import logging
import h5py
import numpy as np
from numpy.random import default_rng
import numpy.ma as ma

'''
Make a mini cosmodc2 catalog suitable for input to skyCatalogs.
Extract lines from the real catalog and rewrite in the same format
'''


class MiniCosmodc2():
    '''
    Given input directories where "regular" cosmodc2 files and associated
    knots files are kept, make mini version by extracting a few rows for
    a single healpixel
    '''
    def __init__(self, input_main_dir, input_knots_dir, output_main_dir,
                 output_knots_dir, hp=9556, n_source=1000,
                 logger=None, loglevel='INFO'):
        self._input_main_dir = input_main_dir
        self._input_knots_dir = input_knots_dir
        self._output_main_dir = output_main_dir
        self._output_knots_dir = output_knots_dir
        self._hp = hp
        self._n_source = n_source
        self._logger = logger
        if not logger:
            self._logger = logging.getLogger('miniCosmodc2')

        if not self._logger.hasHandlers():
            self._logger.setLevel(loglevel)
            ch = logging.StreamHandler()
            ch.setLevel(loglevel)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            ch.setFormatter(formatter)
            self._logger.addHandler(ch)

    def _copy_group(self, in_group, out_group):
        # Used to copy metaData group from main file
        # GCRCatalogs may try to access at least the version
        # keys keys versionMajor, versionMinor and versionMinorMinor
        for k in in_group.keys():
            if isinstance(in_group[k], h5py._hl.group.Group):
                out_sub = out_group.create_group(k)

                self._logger.debug(f'Created group {out_sub.name}')
                self._copy_group(in_group[k], out_sub)
            else:
                new_ds = out_group.create_dataset(k,
                                                  dtype=in_group[k].dtype,
                                                  data=in_group[k])
                self._logger.debug(f'Created dataset {new_ds.name}')
        return

    def _write_selected(self, output_dir, step, hp, select):
        '''
        Write text file of indices of those rows selected for our mini file.

        output_dir   Where to write the file.  Typically with main image file
        step         E.g.  '0_1'
        hp           healpix id
        select       array of ints to be written
        '''
        # First sort select and eliminate any duplicates
        select_sort = select
        select_sort.sort()
        unique = [select_sort[0]]
        for k in range(1, len(select)):
            if select_sort[k] != select_sort[k - 1]:
                unique.append(select_sort[k])

        # Generate output file path
        name = f'selected_rows_{step}_hp{hp}.txt'
        with open(os.path.join(output_dir, name), 'w') as f:
            f.write('# rows selected from original corresponding hdf5 file\n')
            for i in unique:
                f.write(f'{i:10d}\n')

        self._logger.info(f'First 10 indices for step {step}, hp {hp}:')
        for k in range(min(10, len(unique))):
            self._logger.info(unique[k])

    def _sparsify_group(self, in_group, out_group, select_mask):
        for k in in_group.keys():
            if isinstance(in_group[k], h5py._hl.group.Group):
                out_sub = out_group.create_group(k)
                self._logger.debug(f'Created group {out_sub.name}')
                self._sparsify_group(in_group[k], out_sub, select_mask)
            else:        # must be dataset
                masked = ma.MaskedArray(in_group[k], mask=select_mask)
                new_ds = out_group.create_dataset(k,
                                                  dtype=in_group[k].dtype,
                                                  data=masked.compressed())

                self._logger.debug(f'Created dataset {new_ds.name}')


    def _create_mini_file(self, input_file, output_dir, select_mask=None,
                          is_main=True):

        # Compute output path
        out_file = os.path.join(output_dir, 'mini_' + os.path.basename(input_file))

        if select_mask is None:
            # just copy and return
            shutil.copyfile(input_file, out_file)
            return

        # Open original and new hdf5 file
        i_file = h5py.File(input_file)
        with h5py.File(out_file, "w") as mini_file:
            if is_main:
                mini_meta = mini_file.create_group('metaData')
                self._copy_group(i_file['metaData'], mini_meta)
                top_name = 'galaxyProperties'
            else:
                top_name = 'knots'

            top_group = mini_file.create_group(top_name)
            self._sparsify_group(i_file[top_name], top_group, select_mask)

        i_file.close()


    def create(self):
        '''
    Main catalog and knots information are kept separately with parallel
    file organization.  For each healpixel there are three files with
    filenames that look like z_M_N.STUFF.healpix_HPNUM.hdf5 where
    (M, N) can only be (0, 1), (1, 2) or (2, 3).  STUFF is "step_all" for
    main files and "knots" for knots files.   HPNUM is the healpix number.

    n_source is the number of sources to extract from each of the three files.
    '''

        # Determine how many sources are in each of the three files. Use
        # the knots files since they're much smaller (Mbytes rather than Gbytes)
        # If there are fewer rows than requested, set to sentinel value 0.
        # In this case we just copy the file
        cnts = {'0_1': 0, '1_2': 0, '2_3': 0}

        kf_inputs = dict()
        main_inputs = dict()

        for s in cnts:
            kf = os.path.join(self._input_knots_dir,
                              f'z_{s}.knots.healpix_{self._hp}.hdf5')
            kf_inputs[s] = kf
            main_inputs[s] = os.path.join(self._input_main_dir,
                                           f'z_{s}.step_all.healpix_{self._hp}.hdf5')
            with h5py.File(kf) as h5_file:
                cnt = len(h5_file['knots']['k_galaxy_id'])
                if cnt > self._n_source:
                    cnts[s] = cnt

        # If n_source is greater than # sources in a file, just use the whole file
        # But typically n_source will be smaller
        # If there are duplicates, just forge ahead with smaller number
        rng = default_rng()
        for s in cnts:
            if cnts[s] > 0:
                select = rng.integers(low=0, high=cnts[s], size=self._n_source)
                self._write_selected(self._output_main_dir, s, self._hp, select)
                the_mask = np.ones(cnts[s], np.bool)
                for i in select:
                    the_mask[i] = False

            else:
                the_mask=None

            self._create_mini_file(kf_inputs[s], self._output_knots_dir,
                                   select_mask=the_mask, is_main=False)
            self._logger.info(f'Wrote knots file for step {s}, hp {self._hp}')

            self._create_mini_file(main_inputs[s], self._output_main_dir,
                                   select_mask=the_mask, is_main=True)
            self._logger.info(f'Wrote main file for step {s}, hp {self._hp}')


if __name__ == '__main__':

    COSMODC2 = '/global/cfs/cdirs/lsst/shared/xgal/cosmoDC2/cosmoDC2_v1.1.4_'
    COSDC2 = '/global/cfs/cdirs/lsst/shared/xgal/cosmoDC2'
    DFLT_MAIN_DIR = os.path.join(
        COSDC2, 'cosmoDC2_v1.1.4_rs_scatter_query_tree_double')
    DFLT_KNOTS_DIR = os.path.join(COSDC2, 'cosmoDC2_v1.1.4_knots_addon')

    parser = argparse.ArgumentParser(
        description='''
    Create mini cosmoDC2 catalog for a single healpixel.''',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--input-main-dir',
                        help='directory containing full "main" files',
                        default=DFLT_MAIN_DIR)
    parser.add_argument('--input-knots-dir',
                        help='directory containing full knots add-on files',
                        default=DFLT_KNOTS_DIR)
    parser.add_argument('--output-main-dir', '--out-main',
                        help='write mini main output files here')
    parser.add_argument('--output-knots-dir', '--out-knots',
                        help='write mini knots output files here')
    parser.add_argument('--pixel', type=int, default=9556,
                        help='Create mini version for this healpix pixel')
    parser.add_argument('--n-select', type=int, default=1000,
                        help='Number of rows to select from original files')
    parser.add_argument('--loglevel', choices=['DEBUG', 'INFO', 'WARNING',
                                               'ERROR', 'CRITICAL'],
                        default='INFO', help='controls log output')

args = parser.parse_args()

mini_creator = MiniCosmodc2(args.input_main_dir, args.input_knots_dir,
                            args.output_main_dir, args.output_knots_dir,
                            hp=args.pixel, n_source=args.n_select,
                            loglevel=args.loglevel)

mini_creator.create()
