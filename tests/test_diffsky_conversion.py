import numpy as np
from astropy.cosmology import FlatLambdaCDM

from skycatalogs_creator.utils.diffsky_utils import (
    DIFFSKY_RUNTIME_COLUMNS,
    angular_size_arcsec,
    ellipticity_components,
    materialize_diffsky_columns,
    observed_redshift,
    sort_diffsky_by_redshift,
)
from skycatalogs_creator.utils.parquet_schema_utils import make_galaxy_schema


def test_runtime_columns_materialize_opencosmo_redshift_producer():
    assert 'redshift' in DIFFSKY_RUNTIME_COLUMNS


def test_diffsky_output_is_stably_sorted_by_hubble_redshift():
    data = {
        'galaxy_id': np.array([11, 12, 13, 14]),
        'redshiftHubble': np.array([0.8, 0.2, 0.2, 0.5]),
    }
    runtime_rows = np.array([101, 102, 103, 104])

    sorted_data, sorted_rows = sort_diffsky_by_redshift(data, runtime_rows)

    np.testing.assert_array_equal(sorted_data['galaxy_id'], [12, 13, 14, 11])
    np.testing.assert_array_equal(
        sorted_data['redshiftHubble'], [0.2, 0.2, 0.5, 0.8])
    np.testing.assert_array_equal(sorted_rows, [102, 103, 104, 101])


def test_observed_redshift_matches_diffsky_convention():
    redshift_true = np.array([0.0, 1.0, 2.0])
    vpec = np.array([0.0, 300.0, -300.0])
    c_km_s = 299792.458
    expected = ((1.0 + redshift_true)
                * np.sqrt((1.0 - vpec/c_km_s)
                          / (1.0 + vpec/c_km_s)) - 1.0)

    np.testing.assert_allclose(
        observed_redshift(redshift_true, vpec), expected)


def test_ellipticity_components():
    ellipticity = np.array([0.0, 0.5, 0.5])
    position_angle = np.array([0.0, 0.0, np.pi/4.0])

    e1, e2 = ellipticity_components(ellipticity, position_angle)

    np.testing.assert_allclose(e1, [0.0, 1.0/3.0, 0.0], atol=1e-15)
    np.testing.assert_allclose(e2, [0.0, 0.0, 1.0/3.0], atol=1e-15)


def test_angular_size_assumes_proper_kpc():
    cosmology = FlatLambdaCDM(H0=70.0, Om0=0.3)
    radius_kpc = np.array([1.0, 4.0])
    redshift = np.array([0.5, 1.0])

    expected = radius_kpc * cosmology.arcsec_per_kpc_proper(redshift).value
    np.testing.assert_allclose(
        angular_size_arcsec(radius_kpc, redshift, cosmology), expected)


def test_materialize_diffsky_columns_uses_stable_schema_names():
    cosmology = FlatLambdaCDM(H0=70.0, Om0=0.3)
    data = {
        'gal_id': np.array([42], dtype=np.int64),
        'ra': np.array([10.0]),
        'ra_obs': np.array([10.01]),
        'dec': np.array([-2.0]),
        'dec_obs': np.array([-1.99]),
        'redshift_true': np.array([0.5]),
        'vpec': np.array([100.0]),
        'shear1': np.array([0.01]),
        'shear2': np.array([-0.02]),
        'kappa': np.array([0.03]),
        'ellipticity_bulge': np.array([0.2]),
        'ellipticity_disk': np.array([0.4]),
        'psi_bulge': np.array([0.1]),
        'psi_disk': np.array([0.2]),
        'r50_bulge_2d': np.array([1.0]),
        'r50_disk_2d': np.array([3.0]),
        'logsm_obs': np.array([10.5]),
    }

    result = materialize_diffsky_columns(data, cosmology)

    assert set(result) == {
        'galaxy_id', 'ra', 'dec', 'ra_true', 'dec_true',
        'redshift', 'redshiftHubble',
        'peculiarVelocity', 'shear1', 'shear2', 'convergence',
        'spheroidHalfLightRadiusArcsec', 'diskHalfLightRadiusArcsec',
        'diskEllipticity1', 'diskEllipticity2',
        'spheroidEllipticity1', 'spheroidEllipticity2',
        'um_source_galaxy_obs_sm',
    }
    assert result['galaxy_id'][0] == 42
    assert result['ra'][0] == data['ra_obs'][0]
    assert result['dec'][0] == data['dec_obs'][0]
    assert result['ra_true'][0] == data['ra'][0]
    assert result['dec_true'][0] == data['dec'][0]
    assert result['convergence'][0] == data['kappa'][0]
    np.testing.assert_allclose(result['um_source_galaxy_obs_sm'], 10**10.5)

    schema_names = set(make_galaxy_schema(
        'test', galaxy_type='diffsky').names)
    assert set(result).union({'MW_rv', 'MW_av'}) == schema_names
