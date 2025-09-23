import os
# import sys
import yaml
# import json
# import pyarrow.parquet as pq
import logging
# from typing import Any
# from collections import namedtuple
from skycatalogs.utils.config_utils import Config, CURRENT_SCHEMA_VERSION
from skycatalogs.utils.config_utils import YamlIncludeLoader
from skycatalogs.utils.config_utils import YamlPassthruIncludeLoader

__all__ = ['create_config',
           'assemble_MW_extinction', 'assemble_cosmology',
           'assemble_provenance', 'assemble_MW_extinction',
           'assemble_file_metadata', 'ConfigWriter']


def create_config(catalog_name, logname=None):
    return Config({'catalog_name': catalog_name}, logname)


# A collection of utilities used by CatalogCreator to assemble and write
# configs
def assemble_cosmology(cosmology):
    d = {k: cosmology.__getattribute__(k) for k in ('Om0', 'Ob0', 'sigma8',
                                                    'n_s') if k in dir(cosmology)}
    d['H0'] = float(cosmology.H0.value)
    return d


def assemble_MW_extinction():
    av = {'mode': 'data'}
    rv = {'mode': 'constant', 'value': 3.1}
    return {'r_v': rv, 'a_v': av}


def assemble_provenance(pkg_root, inputs={}, run_options=None,
                        schema_version=None):
    '''
    Assemble provenance information, usually pertaining to a sinlge
    object type

    Parameters
    ----------
    pkg_root  string
        top directory of the git package
    inputs    dict
        For a name like 'star_truth' the path to the corresponding input file.
    run_options dict or None
         Options the script create_sc.py was called with
    schema_verion string or None
         If None (usual case) use current schema version

    Return
    ------
    dict
    '''
    import skycatalogs
    try:
        import git
        have_git = True
    except ImportError:
        have_git = False

    if not schema_version:
        schema_version = CURRENT_SCHEMA_VERSION
    version_d = {'schema_version': schema_version}
    if '__version__' in dir(skycatalogs):
        code_version = skycatalogs.__version__
    else:
        code_version = 'unknown'
    version_d['code_version'] = code_version

    to_return = dict()

    if have_git:
        repo = git.Repo(pkg_root)
        has_uncommited = repo.is_dirty()
        has_untracked = (len(repo.untracked_files) > 0)

        git_d = {}
        git_d['git_hash'] = repo.commit().hexsha
        git_d['git_branch'] = repo.active_branch.name
        status = []
        if has_uncommited:
            status.append('UNCOMMITTED_FILES')
        if has_untracked:
            status.append('UNTRACKED_FILES')
        if len(status) == 0:
            status.append('CLEAN')
        git_d['git_status'] = status

        to_return['versioning'] = version_d
        to_return['skyCatalogs_repo'] = git_d

    if inputs:
        to_return['inputs'] = inputs
    if run_options:
        to_return['run_options'] = run_options

    return to_return


def assemble_file_metadata(pkg_root, inputs=None, run_options=None,
                           flux_file=False, throughputs_versions=None):
    '''
    Assemble the metadata to be included in a skyCatalogs binary data file
    '''
    to_return = assemble_provenance(pkg_root, inputs=inputs,
                                    run_options=run_options)
    if flux_file:
        # add a section 'flux_dependencies' containing at least
        # galsim version and, if possible, throughputs version
        to_return['flux_dependencies'] = dict()
        from galsim import version as galsim_version
        to_return['flux_dependencies']['galsim_version'] = galsim_version
        if throughputs_versions:
            for k, v in throughputs_versions.items():
                to_return['flux_dependencies'][k] = v

    return to_return


def _read_yaml(inpath, silent=True, resolve_include=True):
    '''
    Parameters
    ----------
    inpath     string            path to file
    silent     boolean           if file not found and silent is true,
                                 return None.  Else raise exception
    resolve_include boolean      if False, return values like
                                 !include star.yaml
                                 literally. If True, replace with content
                                 of references file

    Returns
    -------
    dict representing contents of file, or None if silent and file not found
    '''
    if resolve_include:
        ldr = YamlIncludeLoader
    else:
        ldr = YamlPassthruIncludeLoader
    try:
        with open(inpath, mode='r') as f:
            data = yaml.load(f, Loader=ldr)
            return data
    except FileNotFoundError as ex:
        if silent:
            return None
        else:
            raise ex


class ConfigWriter:
    '''
    Saves a little context needed by utilities
    '''
    def __init__(self, skycatalog_root, catalog_dir, top_name,
                 overwrite=False, logname=None):
        self._skycatalog_root = skycatalog_root
        self._catalog_dir = catalog_dir
        self._out_dir = os.path.join(skycatalog_root, catalog_dir)
        self._top_name = top_name
        self._overwrite = overwrite
        if not logname:
            logname = 'skyCatalogs:ConfigUtils'
        self._logger = logging.getLogger(logname)

    def write_yaml(self, input_dict, outpath):
        '''
        Write yaml file if
          * it doesn't already exist     or
          * we're allowed to overwrite

        Parameters
        ----------
        input_dict    dict   Contents to be output to yaml
        outpath       string Where to write the output

        Returns
        -------
        output path (same as argument) if a file is written, else None
        '''
        if self._overwrite:
            return self.update_yaml(input_dict, outpath)

        try:
            with open(outpath, mode='x') as f:
                yaml.dump(input_dict, f)
        except FileExistsError:
            txt = 'write_yaml: Will not overwrite pre-existing config'
            self._logger.warning(txt + outpath)
            return None

        return outpath

    def update_yaml(self, input_dict, outpath):
        '''
        Write yaml regardless of whether file is present or not
        '''
        with open(outpath, mode='w') as f:
            yaml.dump(input_dict, f)
        return outpath

    def find_schema_version(self, top):
        if 'schema_version' not in top.keys():
            return None
        return top['schema_version']

    def schema_compatible(self, schema_version):
        # For now just require that major versions match
        # Schema designations are of the form M.m.p where M, m  and p are
        # integers denoting major, minor and patch version
        current = CURRENT_SCHEMA_VERSION.split('.')
        incoming = schema_version.split('.')
        return current[0] == incoming[0]

    def write_configs(self, config_fragment):
        '''
        Write yaml fragment for specified object type and write or update
        top yaml file if
        * fragment doesn't already exist
        * or overwrite is true

        Parameters
        ----------
        config_fragment   BaseConfigFragment   Knows how to create
                                               config_fragment for a particular
                                               object type
        '''

        # Need the following machinery (class IncludeValue; routine
        # include_representer) in order to output values like
        #       !include  some_path.yaml
        # properly
        class IncludeValue(str):
            def __new__(cls, a):
                return str.__new__(cls, a)

            def __repr__(self):
                return "IncludeValue(%s)" % self

        def include_representer(dumper, value):
            # To avoid outputting any quotes, use style='|'
            return dumper.represent_scalar(u'!include', u'%s' % value,
                                           style='|')

        overwrite = self._overwrite
        top_path = os.path.join(self._out_dir, self._top_name + '.yaml')

        top = _read_yaml(top_path, silent=True, resolve_include=False)
        if top:
            top_exists = True
            object_type_exists = config_fragment.object_type in top['object_types']
            schema_version = self.find_schema_version(top)
        else:
            top_exists = False
            object_type_exists = False
            schema_version = None

        if top_exists:
            if not self.schema_compatible(schema_version):
                if not overwrite:
                    raise RuntimeError('Incompatible skyCatalogs config versions')
                else:
                    self._logger.warning('Overwriting config with incompatible schema version')
            if object_type_exists and not overwrite:
                return

        # Generate and write fragment for the object type
        fragment_name = config_fragment.fragment_name
        frag = config_fragment.make_fragment()
        frag_path = os.path.join(self._out_dir, fragment_name)
        self.write_yaml(frag, frag_path)

        # Write or update top file if necessary
        object_type = config_fragment.object_type
        value = IncludeValue(fragment_name)
        yaml.add_representer(IncludeValue, include_representer)
        if top_exists and not overwrite:
            if object_type_exists and top['object_types'][object_type] == value:
                # No change necessary
                return

            # Otherwise need to add or modify value for our object type
            # First have to fix values for any other object types already
            # mentions.  Value read in looks like "!include an_obj_type.yaml"
            for k, v in top['object_types'].items():
                cmps = v.split(' ')
                new_value = IncludeValue(cmps[1])
                top['object_types'][k] = new_value

            top['object_types'][object_type] = value
            self.update_yaml(top, top_path)
            return

        # Write out top file from scratch, ignoring other object types
        # which may have been referenced in older version
        top_dict = {'skycatalog_root': self._skycatalog_root,
                    'catalog_dir': self._catalog_dir,
                    'catalog_name': self._top_name,
                    'schema_version': CURRENT_SCHEMA_VERSION}
        objs = {object_type: value}
        top_dict['object_types'] = objs
        self.write_yaml(top_dict, top_path)
