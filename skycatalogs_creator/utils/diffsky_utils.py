"""Conversions and portable runtime state for current Diffsky catalogs."""

from pathlib import Path
import shutil

import numpy as np


_C_KM_S = 299792.458

# Native model parameters consumed by
# ``compute_dbk_seds_from_diffsky_mock``.  Keeping these in compact OpenCosmo
# sidecars lets skyCatalogs recompute SEDs without the original mock directory.
DIFFSKY_RUNTIME_COLUMNS = (
    # ``redshift`` is an OpenCosmo-derived companion of ``redshift_true``.
    # Request it explicitly even though the SED calculation only consumes
    # redshift_true.  Older OpenCosmo writers otherwise retain its producer
    # but omit its evaluated value, and fail in make_schema with
    # ``KeyError: 'redshift'``.
    'gal_id', 'redshift', 'redshift_true', 'central', 'top_host_idx',
    'mc_sfh_type',
    'fknot', 'uran_fbulge', 'uran_av', 'uran_delta', 'uran_funo',
    'uran_pburst', 'uran_pmerge', 'delta_mag_ssp_scatter', 'logm0',
    'logtc', 'early_index', 'late_index', 't_peak', 'logmp_infall',
    'logmhost_infall', 'lgmcrit', 'lgy_at_mcrit', 'indx_lo', 'indx_hi',
    'lg_qt', 'qlglgdt', 'lg_drop', 'lg_rejuv',
)

DIFFSKY_MAIN_COLUMNS = (
    'gal_id', 'ra', 'ra_obs', 'dec', 'dec_obs', 'redshift_true', 'vpec',
    'shear1', 'shear2', 'kappa', 'ellipticity_bulge', 'ellipticity_disk',
    'psi_bulge', 'psi_disk', 'r50_bulge_2d', 'r50_disk_2d', 'logsm_obs',
)


def select_diffsky_pixel(catalog, pixel, magnitude_cut, cosmology):
    """Select and translate one observed-coordinate NSIDE=32 pixel."""
    import healpy

    ring_pixels = np.append(
        pixel, healpy.get_all_neighbours(32, pixel, nest=False))
    ring_pixels = np.unique(ring_pixels[ring_pixels >= 0])
    selected = catalog.pixel_search(
        healpy.ring2nest(32, ring_pixels), nside=32)
    columns = list(DIFFSKY_MAIN_COLUMNS)
    if magnitude_cut:
        columns.append('lsst_r')
    raw = selected.select(columns).get_data(
        format='numpy', wrap_single=True)

    in_pixel = (healpy.ang2pix(
        32, raw['ra_obs'], raw['dec_obs'], lonlat=True) == pixel)
    runtime_rows = np.flatnonzero(in_pixel)
    raw = {name: np.asarray(values)[runtime_rows]
           for name, values in raw.items()}
    if magnitude_cut:
        keep = np.asarray(raw.pop('lsst_r')) < magnitude_cut
        runtime_rows = runtime_rows[keep]
        raw = {name: np.asarray(values)[keep]
               for name, values in raw.items()}
    return materialize_diffsky_columns(raw, cosmology), selected, runtime_rows


def sort_diffsky_by_redshift(data, runtime_rows):
    """Apply one stable Hubble-redshift ordering to catalog and state."""
    if not data:
        return data, runtime_rows
    order = np.argsort(np.asarray(data['redshiftHubble']), kind='stable')
    return ({name: np.asarray(values)[order]
             for name, values in data.items()},
            np.asarray(runtime_rows)[order])


def _compact_spatial_tree(dataset):
    """Replace a selected dataset's large index with its level-zero index.

    OpenCosmo needs an index to reconstruct a lightcone region when reopening
    a file, but its normal writer serializes every HEALPix level.  Runtime
    state is selected by galaxy id, so the twelve-cell level-zero index is
    sufficient and avoids hundreds of megabytes of zero-filled index arrays.
    """
    import opencosmo as oc

    tree = dataset.tree
    if tree is None:
        return dataset
    tree = tree.apply_index(dataset.index)
    compact_tree = type(tree)(
        tree._Tree__index,
        {key: tree._Tree__columns[key]
         for key in ('level_0', 'level_0/start', 'level_0/size')},
    )
    return oc.Dataset(dataset.header, dataset._Dataset__state,
                      tree=compact_tree)


def _compact_runtime_state(value):
    """Recursively retain linked OpenCosmo data while compacting its trees."""
    import opencosmo as oc

    if isinstance(value, oc.Dataset):
        return _compact_spatial_tree(value)
    if isinstance(value, oc.Lightcone):
        return oc.Lightcone(
            {key: _compact_runtime_state(item)
             for key, item in value.items()},
            value.z_range, value._Lightcone__hidden,
            value._Lightcone__sort_key,
        )
    if isinstance(value, oc.StructureCollection):
        return oc.StructureCollection(
            _compact_runtime_state(value._StructureCollection__source),
            {key: _compact_runtime_state(item) for key, item in
             value._StructureCollection__datasets.items()},
            hide_source=value._StructureCollection__hide_source,
            link_handler=value._StructureCollection__handler,
            derived_columns=value._StructureCollection__derived_columns,
        )
    raise TypeError(f'Unsupported OpenCosmo value {type(value)!r}')


def initialize_diffsky_runtime_state(source_dir, output_dir, overwrite=False):
    """Copy the shared Diffsky model inputs into the SkyCatalog directory."""
    source_dir = Path(source_dir)
    runtime_dir = Path(output_dir) / 'diffsky_runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    aux_paths = [path for path in source_dir.glob('*.hdf5')
                 if not path.stem.endswith('diffsky_gals')]
    if not aux_paths:
        raise FileNotFoundError(
            f'No Diffsky auxiliary HDF5 files found in {source_dir}')
    for source_path in aux_paths:
        target_path = runtime_dir / source_path.name
        if overwrite or not target_path.exists():
            shutil.copy2(source_path, target_path)
    return runtime_dir


def write_diffsky_runtime_pixel(selected, row_indices, output_dir, pixel,
                                overwrite=False):
    """Write minimal native Diffsky state needed by one output pixel."""
    import opencosmo as oc

    pixel_dir = Path(output_dir) / 'diffsky_runtime' / f'pixel_{pixel}'
    if pixel_dir.exists():
        if not overwrite:
            return pixel_dir
        shutil.rmtree(pixel_dir)
    pixel_dir.mkdir(parents=True)

    rows = np.asarray(row_indices, dtype=np.int64)
    if len(rows) == 0:
        return pixel_dir
    state = selected.take_rows(np.sort(rows)).select(
        list(DIFFSKY_RUNTIME_COLUMNS))
    state = _compact_runtime_state(state)
    for part, dataset in state.items():
        path = pixel_dir / f'pixel_{pixel}_{part}.diffsky_gals.hdf5'
        oc.write(path, dataset)
    return pixel_dir


def observed_redshift(redshift_hubble, peculiar_velocity):
    """Return redshift including the Diffsky line-of-sight velocity.

    This follows ``diffsky.experimental.lc_utils.get_z_obs_from_z_true``.
    Diffsky's line-of-sight velocity sign convention gives the inverse
    relativistic Doppler factor relative to the commonly written recession
    velocity expression.
    """
    velocity_fraction = np.asarray(peculiar_velocity) / _C_KM_S
    doppler_factor = np.sqrt(
        (1.0 - velocity_fraction) / (1.0 + velocity_fraction)
    )
    return (1.0 + np.asarray(redshift_hubble)) * doppler_factor - 1.0


def ellipticity_components(ellipticity, position_angle):
    """Convert Diffsky distortion and position angle to GalSim shear."""
    reduced_ellipticity = np.asarray(ellipticity) / (
        2.0 - np.asarray(ellipticity)
    )
    twice_angle = 2.0 * np.asarray(position_angle)
    return (reduced_ellipticity * np.cos(twice_angle),
            reduced_ellipticity * np.sin(twice_angle))


def angular_size_arcsec(radius_kpc, redshift_hubble, cosmology):
    """Convert a proper physical radius in kpc to an angular size.

    The interpretation of the native Diffsky ``r50_*_2d`` values as proper
    kpc is an explicit input-catalog assumption kept in this helper so it can
    be revised independently if the upstream convention changes.
    """
    arcsec_per_kpc = cosmology.arcsec_per_kpc_proper(
        np.asarray(redshift_hubble)
    ).value
    return np.asarray(radius_kpc) * arcsec_per_kpc


def materialize_diffsky_columns(data, cosmology):
    """Translate current Diffsky columns to the stable SkyCatalog schema."""
    disk_e1, disk_e2 = ellipticity_components(
        data['ellipticity_disk'], data['psi_disk'])
    bulge_e1, bulge_e2 = ellipticity_components(
        data['ellipticity_bulge'], data['psi_bulge'])
    redshift_hubble = np.asarray(data['redshift_true'])

    return {
        'galaxy_id': np.asarray(data['gal_id']),
        'ra': np.asarray(data['ra_obs']),
        'dec': np.asarray(data['dec_obs']),
        'ra_true': np.asarray(data['ra']),
        'dec_true': np.asarray(data['dec']),
        'redshift': observed_redshift(redshift_hubble, data['vpec']),
        'redshiftHubble': redshift_hubble,
        'peculiarVelocity': np.asarray(data['vpec']),
        'shear1': np.asarray(data['shear1']),
        'shear2': np.asarray(data['shear2']),
        'convergence': np.asarray(data['kappa']),
        'spheroidHalfLightRadiusArcsec': angular_size_arcsec(
            data['r50_bulge_2d'], redshift_hubble, cosmology),
        'diskHalfLightRadiusArcsec': angular_size_arcsec(
            data['r50_disk_2d'], redshift_hubble, cosmology),
        'diskEllipticity1': disk_e1,
        'diskEllipticity2': disk_e2,
        'spheroidEllipticity1': bulge_e1,
        'spheroidEllipticity2': bulge_e2,
        'um_source_galaxy_obs_sm': np.power(10.0, data['logsm_obs']),
    }
