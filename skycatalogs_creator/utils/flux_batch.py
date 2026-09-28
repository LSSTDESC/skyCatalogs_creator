"""Bounded-memory flux calculation for catalog row groups."""

from datetime import timedelta
import time

from skycatalogs.objects.base_object import LSST_BANDS, ROMAN_BANDS


def calculate_flux_chunk(object_collection, instrument_needed, lower, upper,
                         id_column):
    """Calculate one flux chunk while retaining only one SED batch."""
    output = {id_column: []}
    lsst_columns = [f'lsst_flux_{band}' for band in LSST_BANDS]
    roman_columns = [f'roman_flux_{band}' for band in ROMAN_BANDS]
    if 'lsst' in instrument_needed:
        output.update({name: [] for name in lsst_columns})
    if 'roman' in instrument_needed:
        output.update({name: [] for name in roman_columns})

    if upper > lower:
        first = object_collection[lower]
        batch_size = (first.sed_prefetch_batch_size
                      if hasattr(first, 'prefetch_seds') else upper - lower)
        del first
    else:
        batch_size = 1

    started = time.perf_counter()
    total = upper - lower
    for start in range(lower, upper, batch_size):
        stop = min(start + batch_size, upper)
        batch = object_collection[start:stop]
        if batch and hasattr(batch[0], 'prefetch_seds'):
            batch[0].prefetch_seds(batch)

        output[id_column].extend(
            obj.get_native_attribute(id_column) for obj in batch)
        if 'lsst' in instrument_needed:
            fluxes = [obj.get_LSST_fluxes(cache=False, as_dict=False)
                      for obj in batch]
            for name, values in zip(lsst_columns, zip(*fluxes)):
                output[name].extend(values)
        if 'roman' in instrument_needed:
            fluxes = [obj.get_roman_fluxes(cache=False, as_dict=False)
                      for obj in batch]
            for name, values in zip(roman_columns, zip(*fluxes)):
                output[name].extend(values)

        completed = stop - lower
        elapsed = time.perf_counter() - started
        rate = completed / elapsed if elapsed else 0.0
        remaining = ((total - completed) / rate
                     if rate else float('inf'))
        print(
            f'Flux progress: {completed:,}/{total:,} '
            f'({100.0 * completed / total:.1f}%); '
            f'elapsed {timedelta(seconds=int(elapsed))}; '
            f'rate {rate:.2f} objects/s; '
            f'ETA {timedelta(seconds=int(remaining))}; '
            f'projected runtime '
            f'{timedelta(seconds=int(elapsed + remaining))}',
            flush=True)

        if batch and hasattr(batch[0], 'clear_prefetched_seds'):
            batch[0].clear_prefetched_seds()
        del batch
    return output
