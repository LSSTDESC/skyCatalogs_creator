import logging

import pyarrow as pa
import pyarrow.parquet as pq

from skycatalogs_creator.flux_catalog_creator import FluxCatalogCreator
from skycatalogs_creator.flux_catalog_creator import _do_flux_chunk


class _PrefetchingObject:
    def __init__(self, object_id, calls):
        self.object_id = object_id
        self.calls = calls

    @property
    def sed_prefetch_batch_size(self):
        return 2

    def prefetch_seds(self, objects):
        self.calls.append([obj.object_id for obj in objects])

    def get_native_attribute(self, name):
        if name == 'redshiftHubble':
            return self.object_id / 10.0
        assert name == 'galaxy_id'
        return self.object_id

    def get_LSST_fluxes(self, cache=True, as_dict=False):
        assert cache is False
        return [self.object_id + index for index in range(6)]


def test_flux_chunk_prefetches_requested_objects_in_consumed_batches():
    calls = []
    objects = [_PrefetchingObject(index, calls) for index in range(5)]
    result = _do_flux_chunk(
        None, objects, ['lsst'], 0, len(objects), 'galaxy_id')

    assert calls == [[0, 1], [2, 3], [4]]
    assert result == {
        'galaxy_id': [0, 1, 2, 3, 4],
        'lsst_flux_u': [0, 1, 2, 3, 4],
        'lsst_flux_g': [1, 2, 3, 4, 5],
        'lsst_flux_r': [2, 3, 4, 5, 6],
        'lsst_flux_i': [3, 4, 5, 6, 7],
        'lsst_flux_z': [4, 5, 6, 7, 8],
        'lsst_flux_y': [5, 6, 7, 8, 9],
    }


def test_flux_chunk_releases_objects_after_each_prefetch_batch():
    class TrackingObject(_PrefetchingObject):
        active = 0
        maximum_active = 0

        def __init__(self, object_id, calls):
            super().__init__(object_id, calls)
            type(self).active += 1
            type(self).maximum_active = max(
                type(self).maximum_active, type(self).active)

        def __del__(self):
            type(self).active -= 1

    class LazyCollection:
        def __init__(self, size, calls):
            self.size = size
            self.calls = calls

        def __getitem__(self, key):
            if isinstance(key, slice):
                return [TrackingObject(index, self.calls)
                        for index in range(key.start, key.stop)]
            return TrackingObject(key, self.calls)

    calls = []
    result = _do_flux_chunk(
        None, LazyCollection(20, calls), ['lsst'], 0, 20, 'galaxy_id')

    assert len(result['galaxy_id']) == 20
    assert TrackingObject.active == 0
    assert TrackingObject.maximum_active <= 2


def test_collection_uses_disposable_chunks_and_preserves_order(tmp_path):
    objects = [_PrefetchingObject(index, []) for index in range(7)]
    schema = pa.schema(
        [pa.field('galaxy_id', pa.int64())]
        + [pa.field(f'lsst_flux_{band}', pa.float32())
           for band in 'ugrizy'])
    output_path = tmp_path / 'flux.parquet'

    creator = FluxCatalogCreator.__new__(FluxCatalogCreator)
    creator._flux_worker_chunk_size = 3
    creator._flux_parallel = 2
    creator._logger = logging.getLogger('test.flux.worker')

    writer, chunks = creator._write_flux_collection(
        objects, ['lsst'], 'galaxy_id', schema, None, output_path)
    writer.close()

    table = pq.read_table(output_path)
    assert chunks == 3
    assert table.num_rows == 7
    assert table.column('galaxy_id').to_pylist() == list(range(7))
    assert pq.ParquetFile(output_path).num_row_groups == 3
