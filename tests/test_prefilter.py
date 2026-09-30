import pytest

from seguro.checks.base import Context
from seguro.checks.prefilter import PrefilterCheck
from seguro.models import Candidate, Result


@pytest.mark.parametrize("domain,ok", [
    ("sportnews.com", True),
    ("sport-news.com", True),
    ("a-b-c.com", False),
    ("news24.com", False),
    ("sportnews.xyz", False),
    ("cheapviagra.com", False),
    ("ab.com", False),
])
async def test_prefilter(config, domain, ok):
    res = Result(domain)
    await PrefilterCheck().run(Candidate(domain), res, Context(config, None))
    assert res.rejected is (not ok)
