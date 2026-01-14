Installation Instructions
=========================

.. note::
   **Prerequisites**:

   All that is required is a reasonably current version of the  `LSST science pipelines <https://pipelines.lsst.io/>`_  and of the `skyCatalogs` package.
   However, in order to generate catalogs for a particular object type some
   suitable source catalog must be read. Depending on the format of that
   catalog, you may need to install an additional library or two.

Installation steps common to all object type
--------------------------------------------

.. note::
   These instructions are similar to imSim installation instructions.  If you've
   installed imSim already you can skip everything in this section except the
   installation of `skyCatalogs_creator` itself and ensuring you have a new
   enough version of `skyCatalogs`.

Installing LSST science pipelines
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
There are several methods of installation.  Only the simplest (using a prebuilt cvmfs version) is described here.  For other methods, see the imSim installation instructions.

If you are working at the USDF (Rubin Project computing) or at NERSC (DESC computing), perhaps the easiest way to setup and use *skyCatalogs_creator* is to rely on the prebuilt versions of the pipelines contained in the cvmfs distribution which is installed there.  This solution is also appropriate for personal laptops and university/lab based computing systems if you are able to install the *cvmfs* system.

The `CernVM file system <https://cvmfs.readthedocs.io/>`_  (cvmfs) is a distributed read-only file system developed at CERN for reliable low-maintenance world-wide software distribution.  LSST-France distributes weekly builds of the Rubin science pipelines for both Linux and MacOS.  Details and installation instructions can  be found at `sw.lsst.eu <https://sw.lsst.eu/index.html>`_ .  The distribution includes conda and skyCatalogs dependencies from conda-forge along with the science pipelines.

.. _setup_pipelines:

Load and setup the science pipelines
++++++++++++++++++++++++++++++++++++

First you need to setup the science pipelines.  This involves sourcing a setup file and then using the Rubin *eups* commands to set them up.

.. note::

   Version  ``w_2025_49`` or later of the science pipelines is recommended. This will guarantee other dependencies of skyCatalogs, such as GalSim, are new enough.

   Also note: the cvmfs distribution is a read-only distribution.  This means you cannot add packages to the included conda environment and packages you install via *pip* will be installed in the user area.  If you need a *conda*  environment you will need to use a different installation method.

Source the appropriate setup script (note the -ext in the name) and then setup the distribution (if you are on MacOS use darwin-x86_64 instead of linux-x86_64).

.. code-block:: sh

   source /cvmfs/sw.lsst.eu/almalinux-x86_64/lsst_distrib/w_2025_28/loadLSST-ext.bash
   setup lsst_distrib


Install skyCatalogs
~~~~~~~~~~~~~~~~~~~

Clone the skyCatalogs package from GitHub.  Here we assume you are in
your installation directory SKYCATALOGS_HOME as described in the section :ref:`per-session` below.

.. code-block:: sh

   git clone https://github.com/LSSTDESC/skyCatalogs

at this point if you would only like to use *skyCatalogs* you can  ``pip install skyCatalog/`` however we instead suggest using the *eups* tool to simply setup the package for use without installing it. This will allow you to edit the package in place, use multiple versions, change branches etc. You should definitely do this if you plan to do any *skyCatalogs* or *skyCatalogs_creator* development.

If you do not intend to do any development you may choose instead to clone or pip install the most recent release tag.  It should be at least v2.4.0.

.. code-block:: sh

   git clone https://github.com/LSSTDESC/skyCatalogs.git --branch v2.4.0

or

.. code-block:: sh

   pip install skyCatalogs

.. _trilegal

Creating trilegal catalogs
~~~~~~~~~~~~~~~~~~~~~~~~~~

In order to create trilegal catalogs you need to install the pystellibs and astro-datalab packages.  You can do something like this:

.. code-block :: sh

   git clone https://github.com/mfouesneau/pystellibs.git
   cd pystellibs
   pip install  --user --no-deps --nobuild-isolation  .
   cd ..
   pip install --no-build-isolation --no-deps astro-datalab


Install skyCatalogs_creator
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: sh

   git clone https://github.com/LSSTDESC/skyCatalogs_creator.git

.. _install-data-files:

Install needed data files
-------------------------
Go to your `SKYCATALOGS_HOME` directory and download some needed data files (you will only need to do this once).

.. code-block:: sh

   mkdir -p rubin_sim_data/sims_sed_library
   curl https://s3df.slac.stanford.edu/groups/rubin/static/sim-data/rubin_sim_data/throughputs_2023_09_07.tgz | tar -C rubin_sim_data -xz
   curl https://s3df.slac.stanford.edu/groups/rubin/static/sim-data/sed_library/seds_170124.tar.gz  | tar -C rubin_sim_data/sims_sed_library -xz


.. _per-session:

Per-session setup
~~~~~~~~~~~~~~~~~

Every session you will need to initialize the lsst pipelines distribution and
define a ``SKYCATALOGS_HOME`` directory where other needed files (see e.g. section :ref:`install-data-files`) go:

.. code-block:: sh

   source /cvmfs/...            # as above
   setup lsst_distrib

   export SKYCATALOGS_HOME=*PUT YOUR INSTALL DIRECTORY HERE*
   setup -k -r $SKYCATALOGS_HOME/skyCatalogs

   # For data files
   export RUBIN_SIM_DATA_DIR=$SKYCATALOGS_HOME/rubin_sim_data
   export SIMS_SED_LIBRARY_DIR=$SKYCATALOGS_HOME/rubin_sim_data/sims_sed_library


If you're creating trilegal catalogs you also need to make pystellibs and
the Astro Datalab software accessible.
You may need to do something like this:

.. code-block:: sh

   export PYTHONPATH=${SKYCATALOGS_HOME}/pystellibs/src:${PYTHONPATH}

Using skyCatalogs
-----------------

You should now be able to import the code you need from the skyCatalogs package, e.g.

.. code-block:: python

   from skycatalogs.skyCatalogs import open_catalog
   from skycatalogs.utils.shapes import Disk

   skycatalog_root = "path_to/skycatalog_files"  # folder containing catalog
   config_file = "some_folder/skyCatalog.yaml"

   cat = open_catalog(config_file, skycatalog_root=skycatalog_root)

   # define disk at ra, dec = 45.0, -9.0 of radius 100 arcseconds
   disk = disk(45.0, -9.0, 100.0)

   # get galaxies and stars in the region
   objects = cat.get_objects_by_region(disk, obj_type_set={'galaxy', 'star'})
