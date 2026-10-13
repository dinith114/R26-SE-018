# Routes package.
#
# Deliberately empty of imports.
#
# This used to say `from . import growth_stage` and `from . import
# bloom_prediction`, which meant importing ANY route module in this package
# loaded Component 2's whole dependency chain - Pillow, python-multipart and
# the ML stack behind them. A test that only checks a freshness window had to
# install TensorFlow to reach the first assert, and CI failed on
# `ModuleNotFoundError: No module named 'PIL'` before running a single test.
#
# The lines were also redundant: main.py imports both modules explicitly and
# registers their routers, so nothing here changes what the running API serves.
