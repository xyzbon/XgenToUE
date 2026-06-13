"""XgenToUE — Maya XGen to Unreal Engine groom exporter."""

__version__ = '1.0.0'

from . import _bootstrap as _bootstrap

# Put the bundled lib/ on sys.path so the vendored Alembic helper (`cask`,
# imported top-level by xgentoue.core.abc_process) resolves whether the tool
# is installed, unzipped, or driven from the dev harness.
_bootstrap.add_lib_dir()

# Prepend the OPTIONAL per-Maya site-packages dir (only present if the user
# dropped trimesh/scipy wheels there) before imports. No-op otherwise - the
# tool is dependency-free and uses the pure-Python BVH by default.
_bootstrap.add_bundled_site_packages()
