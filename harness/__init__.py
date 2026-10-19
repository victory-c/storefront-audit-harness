"""storefront-audit-harness — runtime harness package.

Step 1 ships only the contract layer (schemas + validation). Crawl/reason/write
phases land in later steps.
"""

from harness.version import HARNESS_VERSION

__all__ = ["HARNESS_VERSION"]
