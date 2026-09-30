from .backlinks import BacklinksCheck
from .base import BaseCheck, Context, Item
from .blacklist import BlacklistCheck
from .index import IndexCheck
from .localists import LocalListsCheck
from .openpagerank import OpenPageRankCheck
from .prefilter import PrefilterCheck
from .rdap import RdapCheck
from .safebrowsing import SafeBrowsingCheck
from .toplists import ToplistsCheck
from .wayback import WaybackCheck


def default_checks() -> list[BaseCheck]:
    """Порядок важливий: спочатку без мережі, потім безкоштовні пакетні, потім по одному
    домену, і лише наприкінці — платні/квотовані."""
    return [
        PrefilterCheck(),
        LocalListsCheck(),
        BlacklistCheck(),
        ToplistsCheck(),
        OpenPageRankCheck(),
        SafeBrowsingCheck(),
        RdapCheck(),
        WaybackCheck(),
        IndexCheck(),
        BacklinksCheck(),
    ]


__all__ = [
    "BacklinksCheck", "BaseCheck", "BlacklistCheck", "Context", "IndexCheck", "Item",
    "LocalListsCheck", "OpenPageRankCheck", "PrefilterCheck", "RdapCheck",
    "SafeBrowsingCheck", "ToplistsCheck", "WaybackCheck", "default_checks",
]
