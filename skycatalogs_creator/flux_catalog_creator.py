import os
import logging
import traceback
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from multiprocessing import Process, Pipe
from .utils.config_creator_utils import assemble_file_metadata
from .utils.parquet_schema_utils import make_galaxy_flux_schema
from .utils.parquet_schema_utils import make_star_flux_schema
from skycatalogs.objects.base_object import load_lsst_bandpasses_version
from skycatalogs.objects.base_object import load_roman_bandpasses_version
from .sso_catalog_creator import SsoFluxCatalogCreator
from .trilegal_catalog_creator import TrilegalFluxCatalogCreator
from .utils.flux_batch import calculate_flux_chunk

"""
Code to create flux sky catalogs for particular object types
"""

__all__ = ['FluxCatalogCreator']

_MW_rv_constant = 3.1
_nside_allowed = 2**np.arange(15)


# Collection of galaxy objects for current row group, current pixel
# Used while doing flux computation
def _do_flux_chunk(send_conn, object_collection, instrument_needed,
                   l_bnd, u_bnd, id_column):
    '''
    send_conn           output connection
    object_collection   objects whose fluxes are to be computed
    instrument_needed   determines which fluxes (LSST only or also Roman)
                        to compute
    l_bnd, u_bnd        demarcates slice to process
    id_column           column name

    returns
                    dict with keys id, lsst_flux_u, ... lsst_flux_y
    '''
    try:
        out_dict = calculate_flux_chunk(
            object_collection, instrument_needed, l_bnd, u_bnd, id_column)
        if send_conn:
            send_conn.send(('result', out_dict))
        else:
            return out_dict
    except BaseException:
        if send_conn:
            send_conn.send(('error', traceback.format_exc()))
        else:
            raise
    finally:
        if send_conn:
            send_conn.close()


class FluxCatalogCreator:
    def __init__(self, object_type, parts,
                 skycatalog_root=None,
                 catalog_dir='.',
                 config_path=None,
                 catalog_name='skyCatalog',
                 logname='skyCatalogs.creator',
                 pkg_root=None,
                 skip_done=False,
                 flux_parallel=16,
                 flux_worker_chunk_size=100000,
                 include_roman_flux=False,
                 diffsky_ssp_wave_min_micron=0.06,
                 diffsky_ssp_wave_max_micron=2.34,
                 diffsky_sed_engine=None,
                 diffsky_sed_precision=None,
                 sso_sed=None,
                 run_options=None):
        """
        Store context for catalog creation

        Parameters
        ----------
        object_type     'cosmodc2_galaxy', 'skysim5000', 'diffsky_galaxy',
                        'star', 'sso' or 'trilegal'
        parts           Segments for which catalog is to be generated. If
                        partition type is HEALpix, parts will be a collection
                        of HEALpix pixels
        skycatalog_root Typically absolute directory containing one or
                        more subdirectories for sky catalogs. Defaults
                        to current directory
        catalog_dir     Directory relative to skycatalog_root where catalog
                        will be written.  Defaults to '.'
        config_path     Where to read config file. Default is data
                        directory.
        catalog_name    If a config file is written this value is saved
                        there and is also part of the filename of the
                        config file.
        logname         logname for Python logger
        pkg_root        defaults to one level up from __file__
        skip_done       If True, skip over files which already exist. Otherwise
                        (by default) overwrite with new version.
                        Output info message in either case if file exists.
        flux_parallel   Number of processes to divide work of computing fluxes
        flux_worker_chunk_size Maximum number of objects computed during one
                        worker process lifetime. Each worker exits after its
                        chunk so native-library memory is returned to the OS.
        # dc2             Whether to adjust values to provide input comparable
        #                to that for the DC2 run
        include_roman_flux Calculate and write Roman flux values
        diffsky_sed_engine Select the optimized ``fast`` implementation or
                           Diffsky's public ``reference`` implementation
        diffsky_sed_precision Arithmetic precision for the optimized engine
        sso_sed         Path to sed file to be used for all SSOs
        run_options     The options the outer script (create_sc.py) was
                        called with

        Might want to add a way to specify template for output file name
        and template for input sedLookup file name.
        """
        from skycatalogs import open_catalog

        self._object_type = object_type
        if object_type.endswith('_galaxy'):
            self._galaxy_type = object_type[:-7]  # len('_galaxy')
        elif object_type == 'skysim5000':
            self._galaxy_type = object_type

        if pkg_root:
            self._pkg_root = pkg_root
        else:
            self._pkg_root = os.path.join(os.path.dirname(__file__), '..')

        self._parts = parts
        if skycatalog_root:
            self._skycatalog_root = skycatalog_root
        else:
            self._skycatalog_root = './'
        if catalog_dir:
            self._catalog_dir = catalog_dir
        else:
            self._catalog_dir = '.'

        self._output_dir = os.path.join(self._skycatalog_root,
                                        self._catalog_dir)

        self._config_path = config_path
        self._catalog_name = catalog_name

        self._cat = open_catalog(self.get_config_file_path(),
                                 skycatalog_root=self._skycatalog_root)
        # if we're not skipping existing files (that is, we're overwriting)
        # and the catalogs are partitioned by healpixel, tell skyCatalogs
        # to ignore existing flux files for the healpixels we process
        if self._object_type == 'cosmodc2_galaxy':
            self._cat.ignore_files('galaxy', self._parts)
        else:
            self._cat.ignore_files(self._object_type, self._parts)

        self._logname = logname
        self._logger = logging.getLogger(logname)
        self._skip_done = skip_done
        self._flux_parallel = flux_parallel
        if flux_parallel < 1:
            raise ValueError('flux_parallel must be at least 1')
        if flux_worker_chunk_size < 1:
            raise ValueError('flux_worker_chunk_size must be at least 1')
        self._flux_worker_chunk_size = flux_worker_chunk_size
        self._include_roman_flux = include_roman_flux
        if self._object_type == 'diffsky_galaxy' and (
                diffsky_sed_engine is not None
                or diffsky_sed_precision is not None):
            factory = self._cat.observed_sed_factory('diffsky_galaxy')
            factory.set_compute_options(
                diffsky_sed_engine, diffsky_sed_precision)
        if self._object_type == 'diffsky_galaxy' and (
                diffsky_ssp_wave_min_micron is not None
                or diffsky_ssp_wave_max_micron is not None):
            factory = self._cat.observed_sed_factory('diffsky_galaxy')
            factory.set_ssp_wave_bounds(
                diffsky_ssp_wave_min_micron,
                diffsky_ssp_wave_max_micron)
        self._obs_sed_factory = None
        self._sso_creator = SsoFluxCatalogCreator(self)
        self._trilegal_creator = TrilegalFluxCatalogCreator(self, include_roman_flux=self._include_roman_flux)
        self._run_options = run_options
        self._tophat_sed_bins = None

    def create(self):
        """
        Create catalog for our object_type, using stored context.

        Return
        ------
        None
        """
        object_type = self._object_type
        if object_type in {'cosmodc2_galaxy', 'diffsky_galaxy', 'skysim5000'}:
            self.create_galaxy_flux_catalog()
        elif object_type == ('star'):
            self.create_pointsource_flux_catalog()
        elif object_type == ('sso'):
            self._sso_creator.create_sso_flux_catalog()
        elif object_type == ('trilegal'):
            self._trilegal_creator.create_trilegal_flux_catalog()

        else:
            raise NotImplementedError(
                f'FluxCatalogCreator.create: unsupported object type {object_type}')

    def create_galaxy_flux_catalog(self, config_file=None):
        '''
        Create a second file per healpixel containing just galaxy id and
        LSST fluxes.  Use information in the main file to compute fluxes

        Parameters
        ----------
        Path to config created in first stage so we can find the main
        galaxy files.

        Return
        ------
        None
        '''

        # Throughput versions for fluxes included
        thru_v = {'lsst_throughputs_version': load_lsst_bandpasses_version()}
        if self._include_roman_flux:
            thru_v['roman_throughputs_version'] = load_roman_bandpasses_version()

        file_metadata = assemble_file_metadata(
            self._pkg_root,
            run_options=self._run_options,
            flux_file=True,
            throughputs_versions=thru_v)

        self._gal_flux_schema =\
            make_galaxy_flux_schema(self._logname, self._galaxy_type,
                                    include_roman_flux=self._include_roman_flux,
                                    metadata_input=file_metadata)
        self._gal_flux_needed = [field.name for field in self._gal_flux_schema]

        if self._galaxy_type == 'diffsky':
            type_field = 'diffsky_galaxy'
        elif self._galaxy_type == 'skysim5000':
            type_field = self._galaxy_type
        else:
            type_field = 'galaxy'
        self._flux_template = self._cat.raw_config['object_types'][type_field]['flux_file_template']

        self._logger.info('Creating galaxy flux files')
        for p in self._parts:
            self._logger.info(f'Starting on pixel {p}')
            self._create_galaxy_flux_pixel(p)
            if self._galaxy_type == 'diffsky':
                self._cat.observed_sed_factory(
                    'diffsky_galaxy').clear_runtime_caches(
                        clear_compiled=True)
            self._logger.info(f'Completed pixel {p}')

    def _get_needed_flux_attrs(self):
        if self._galaxy_type == 'diffsky':
            return ['galaxy_id', 'shear1', 'shear2', 'convergence',
                    'redshiftHubble', 'ra_true', 'dec_true',
                    'MW_av', 'MW_rv']
        else:
            return ['galaxy_id', 'shear_1', 'shear_2', 'convergence',
                    'redshift_hubble', 'MW_av', 'MW_rv', 'sed_val_bulge',
                    'sed_val_disk', 'sed_val_knots']

    def _write_flux_collection(self, object_collection, instrument_needed,
                               id_column, schema, writer, output_path):
        """Compute and write one collection using disposable workers."""
        ranges = [
            (lower, min(lower + self._flux_worker_chunk_size,
                        len(object_collection)))
            for lower in range(0, len(object_collection),
                               self._flux_worker_chunk_size)
        ]
        self._logger.info(
            f'Processing {len(object_collection):,} objects in '
            f'{len(ranges)} disposable worker chunk(s), with up to '
            f'{self._flux_parallel} worker(s) concurrently')

        for wave_start in range(0, len(ranges), self._flux_parallel):
            wave = ranges[wave_start:wave_start + self._flux_parallel]
            workers = []
            try:
                for i, (lower, upper) in enumerate(wave):
                    conn_rd, conn_wrt = Pipe(duplex=False)
                    proc = Process(
                        target=_do_flux_chunk,
                        name=f'flux_{lower}_{upper}',
                        args=(conn_wrt, object_collection,
                              instrument_needed, lower, upper, id_column))
                    proc.start()
                    conn_wrt.close()
                    workers.append((proc, conn_rd, lower, upper))

                # Receive and write in range order so catalog ordering is
                # deterministic even when workers finish out of order.
                for proc, reader, lower, upper in workers:
                    try:
                        status, payload = reader.recv()
                    except EOFError as exc:
                        proc.join()
                        raise RuntimeError(
                            f'Flux worker for [{lower}, {upper}) exited '
                            f'without returning a result '
                            f'(exit code {proc.exitcode})') from exc
                    finally:
                        reader.close()
                    proc.join()
                    if proc.exitcode != 0 and status != 'error':
                        raise RuntimeError(
                            f'Flux worker for [{lower}, {upper}) exited with '
                            f'code {proc.exitcode}')
                    if status == 'error':
                        raise RuntimeError(
                            f'Flux worker for [{lower}, {upper}) failed:\n'
                            f'{payload}')

                    out_table = pa.Table.from_pydict(payload, schema=schema)
                    if writer is None:
                        writer = pq.ParquetWriter(output_path, schema)
                    writer.write_table(out_table)
                    del out_table, payload
                for proc, _, _, _ in workers:
                    proc.close()
            except BaseException:
                for proc, reader, _, _ in workers:
                    reader.close()
                    try:
                        if proc.is_alive():
                            proc.terminate()
                        proc.join()
                        proc.close()
                    except ValueError:
                        # The process may already have been closed after its
                        # result was successfully written.
                        pass
                raise

        return writer, len(ranges)

    def _create_galaxy_flux_pixel(self, pixel):
        '''
        Create a parquet file for a single healpix pixel containing only
        galaxy id and LSST fluxes

        Parameters
        ----------
        Pixel         int

        Return
        ------
        None
        '''

        # Would be better to obtain output filename from config or
        # at least from object_type
        prefix = {
            'diffsky': 'diffsky_galaxy',
            'skysim5000': 'skysim5000',
        }.get(self._galaxy_type, 'galaxy')
        output_filename = f'{prefix}_flux_{pixel}.parquet'
        output_path = os.path.join(self._output_dir, output_filename)

        if os.path.exists(output_path):
            if not self._skip_done:
                self._logger.info(f'Overwriting {output_path}')
            else:
                self._logger.info(f'Skipping regeneration of {output_path}')
                return

        # If there are multiple row groups, each is stored in a separate
        # object collection. Need to loop over them
        object_list = self._cat.get_object_type_by_hp(pixel, self._object_type)
        if len(object_list) == 0:
            self._logger.warning(f'Cannot create flux file for pixel {pixel} because main file does not exist or is empty')
            return

        writer = None
        _instrument_needed = []
        rg_written = 0
        for field in self._gal_flux_needed:
            if 'lsst' in field and 'lsst' not in _instrument_needed:
                _instrument_needed.append('lsst')
            if 'roman' in field and 'roman' not in _instrument_needed:
                _instrument_needed.append('roman')

        for object_coll in object_list.get_collections():
            _galaxy_collection = object_coll
            needed_flux_attrs = self._get_needed_flux_attrs()
            # prefetch everything we need.
            for att in needed_flux_attrs:
                _ = object_coll.get_native_attribute(att)
            writer, _ = self._write_flux_collection(
                _galaxy_collection, _instrument_needed, 'galaxy_id',
                self._gal_flux_schema, writer, output_path)

            if self._galaxy_type == 'diffsky':
                self._cat.observed_sed_factory(
                    'diffsky_galaxy').clear_sed_cache()

            # ObjectList retains every row-group collection. Remove arrays
            # explicitly prefetched for this calculation so they do not
            # accumulate as later row groups are processed.
            for att in needed_flux_attrs:
                if hasattr(object_coll, att):
                    delattr(object_coll, att)
            rg_written += 1

        if writer is not None:
            writer.close()
        self._logger.debug(f'# row groups written to flux file: {rg_written}')

    def create_pointsource_flux_catalog(self, config_file=None):
        '''
        Create a second file per healpixel containing just id and
        LSST fluxes.  Use information in the main file to compute fluxes

        Parameters
        ----------
        Path to config created in first stage so we can find the main
        star files

        Return
        ------
        None
        '''
        thru_v = {'lsst_throughputs_version': load_lsst_bandpasses_version()}
        file_metadata = assemble_file_metadata(
            self._pkg_root,
            run_options=self._run_options,
            flux_file=True,
            throughputs_versions=thru_v)

        self._ps_flux_schema = make_star_flux_schema(self._logname,
                                                     include_roman_flux=self._include_roman_flux,
                                                     metadata_input=file_metadata)

        self._ps_flux_needed = [field.name for field in self._ps_flux_schema]
        self._flux_template = self._cat.raw_config['object_types']['star']['flux_file_template']

        self._logger.info('Creating pointsource flux files')
        for p in self._parts:
            self._logger.info(f'Starting on pixel {p}')
            self._create_pointsource_flux_pixel(p)
            self._logger.info(f'Completed pixel {p}')

    def _create_pointsource_flux_pixel(self, pixel):
        '''
        Create a parquet file for a single healpix pixel containing only
        pointsource id and LSST fluxes

        Parameters
        ----------
        pixel         int

        Return
        ------
        None
        '''

        # For main catalog use self._cat
        # For schema use self._ps_flux_schema
        # output_template should be derived from value for flux_file_template
        #  in main catalog config.  Cheat for now
        output_filename = f'pointsource_flux_{pixel}.parquet'
        output_path = os.path.join(self._output_dir, output_filename)

        if os.path.exists(output_path):
            if not self._skip_done:
                self._logger.info(f'Overwriting {output_path}')
            else:
                self._logger.info(f'Skipping regeneration of {output_path}')
                return
        object_list = self._cat.get_object_type_by_hp(pixel, 'star')
        writer = None
        instrument_needed = []
        for field in self._ps_flux_needed:
            if 'lsst' in field and 'lsst' not in instrument_needed:
                instrument_needed.append('lsst')
            if 'roman' in field and 'roman' not in instrument_needed:
                instrument_needed.append('roman')
        rg_written = 0
        for _star_collection in object_list.get_collections():
            writer, _ = self._write_flux_collection(
                _star_collection, instrument_needed, 'id',
                self._ps_flux_schema, writer, output_path)
            rg_written += 1

        if writer is not None:
            writer.close()
        self._logger.debug(f'# row groups written to flux file: {rg_written}')

    def get_config_file_path(self):
        '''
        Return full path to config file.
        (self._config_path is path to *directory* containing config file)
        '''
        if not self._config_path:
            self._config_path = self._output_dir

        return os.path.join(self._config_path, self._catalog_name + '.yaml')
