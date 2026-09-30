from .backlinks import BacklinksCheck
from .base import Check, Context
from .blacklist import BlacklistCheck
from .prefilter import PrefilterCheck
from .rdap import RdapCheck
from .wayback import WaybackCheck


def default_checks() -> list[Check]:
    """Порядок важливий: від дешевих до дорогих."""
    return [PrefilterCheck(), BlacklistCheck(), RdapCheck(), WaybackCheck(), BacklinksCheck()]


__all__ = [
    "BacklinksCheck", "BlacklistCheck", "Check", "Context", "PrefilterCheck",
    "RdapCheck", "WaybackCheck", "default_checks",
]
