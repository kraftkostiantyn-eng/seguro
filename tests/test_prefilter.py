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


async def test_prefilter_extra_thresholds(config):
    config["prefilter"]["min_extra"] = {"DP": 5}
    config["prefilter"]["max_extra"] = {"aby": 2018}
    ctx = Context(config, None)

    weak = Result("weak.com")
    await PrefilterCheck().run(Candidate("weak.com", extra={"DP": "3"}), weak, ctx)
    assert weak.rejected and "DP=3" in weak.reject_reason

    young = Result("young.com")
    await PrefilterCheck().run(Candidate("young.com", extra={"ABY": "2021", "DP": "1,200"}), young, ctx)
    assert young.rejected and "aby" in young.reject_reason

    fine = Result("fine.com")
    await PrefilterCheck().run(Candidate("fine.com", extra={"DP": "1,200", "ABY": "n/a"}), fine, ctx)
    assert not fine.rejected
