# import os
# from pathlib import Path
from skycatalogs_creator.main_catalog_creator import MainCatalogCreator
from skycatalogs_creator.flux_catalog_creator import FluxCatalogCreator
# from skycatalogs.utils.common_utils import callinfo_to_dict
# PACKAGE_DIR = os.path.dirname(os.path.abspath(str(Path(__file__).parent)))

# Note: environment variable CI_GCR should be
# <pkg_root>/skycatalogs_creator/data/ci_sample
#
pixels = [9556]
object_type = 'cosmodc2_galaxy'

# Output just goes in current directory.  Move by hand when have verified
# it's ok
skycatalog_root = '.'
truth = 'GCR_CI'      # special value
# run_options = {'pixels': pixels, 'object_type': object_type,
#                'skycatalog_root': skycatalog_root, truth: truth}
# opt_dict = callinfo_to_dict(run_options)

main_creator = MainCatalogCreator(object_type, pixels,
                                  skycatalog_root=skycatalog_root,
                                  truth=truth)

main_creator.create()

print('Done with main catalog')

flux_creator = FluxCatalogCreator(object_type, pixels,
                                  skycatalog_root=skycatalog_root)
flux_creator.create()

print('Done with flux catalog')
