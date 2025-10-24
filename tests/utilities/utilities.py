from collections import OrderedDict
import pyarrow.parquet as pq
import pyarrow as pa
import pandas as pd
import numpy as np
import numpy.ma as ma


def compare(file1, file2, object_type='trilegal', cat_type='main',
            exact=True, debug=False):
    if object_type == 'pointsource':
        obj = 'star'
    else:
        obj = object_type

    cols = []
    if cat_type == 'flux':
        cols.append('lsst_flux_r')
        if obj.endswith('galaxy'):
            cols.append('galaxy_id')
        else:
            cols.append('id')
    else:      # main
        cols.extend(['ra', 'dec'])
        if obj.endswith('galaxy'):
            cols.extend(['galaxy_id', 'MW_av', 'redshift'])
        elif obj == 'star':
            cols.extend(['id', 'MW_av', 'magnorm'])
        elif obj == 'sso':
            cols.extend(['id', 'mjd', 'trailed_source_mag'])
        elif obj == 'trilegal':
            cols.extend(['id', 'logT', 'imag'])

    # Keep track of which columns are floating point.  Exact match might
    # not be a reasoable condition
    floats = ['ra', 'dec', 'MW_av', 'redshift', 'magnorm',
              'trailed_source_mag', 'logT', 'imag', 'lsst_flux_r']
    pq_file1 = pq.ParquetFile(file1)
    pq_file2 = pq.ParquetFile(file2)

    n_row_1 = pq_file1.metadata.num_rows
    n_row_2 = pq_file2.metadata.num_rows

    if debug:
        print(f'{n_row_1} rows in {file1}')
        print(f'{n_row_2} rows in {file2}')

    assert n_row_1 == n_row_2

    # Number of rows should be small so it's safe to assume a single row group.
    tbl1 = pq_file1.read_row_group(0, columns=cols)
    tbl2 = pq_file2.read_row_group(0, columns=cols)

    for c in cols:
        if debug:
            print(f'Comparing column {c}')
        if c in floats:
            assert np.isclose(np.array(tbl1[c], dtype="float32"),
                              np.array(tbl2[c], dtype="float32"), atol=0,
                              equal_nan=True).all()
        else:
            assert tbl1[c] == tbl2[c]

        if debug:
            print(f"Column {c} is identical")


def write_selected(input_path, output_path, selected, debug=False):
    '''
    Parameters
    ----------
    input_path    string     Input parquet file to be sparsified
    output_path   string
    selected      list(int)   Which rows to preserve in output
    '''

    in_file = pq.ParquetFile(input_path)
    n_gp = in_file.metadata.num_row_groups
    if debug:
        print('write_selected')
        print(f'Selecting {len(selected)} objects')
        print(f'Input file has {n_gp} row groups')
    schema = in_file.schema
    rgp = in_file.read_row_group(0)

    # file schema consists of column schemas. If the column has structure
    # the name we want is at the start of column schema 'path' attribute
    out_dict = OrderedDict({col.path.split('.')[0]: [] for col in schema})
    offset = 0
    i_gp = 0

    while i_gp < n_gp:
        rgp = in_file.read_row_group(i_gp)
        rg_len = len(rgp)
        rgp_selected = [(i - offset) for i in selected if i >= offset and i < offset + rg_len]
        if len(rgp_selected) > 0:
            # mask off everything except random selection
            m_l = [i not in rgp_selected for i in range(rg_len)]
            m = ma.make_mask(m_l)

            for k in out_dict.keys():
                more = ma.MaskedArray(np.array(rgp[k]), m).compressed()
                out_dict[k] += list(more)

        i_gp += 1
        offset += rg_len

    arrow_schema = schema.to_arrow_schema()
    writer = pq.ParquetWriter(output_path, arrow_schema)

    out_df = pd.DataFrame.from_dict(out_dict)
    out_table = pa.Table.from_pandas(out_df, schema=arrow_schema)

    writer.write_table(out_table)
    writer.close()
