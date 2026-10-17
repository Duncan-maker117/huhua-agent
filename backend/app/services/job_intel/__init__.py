"""岗位情报公共入口；所有结果是招聘参考，不是用户事实。"""

from .providers import (
    DeepSeekProvider,
    TavilyProvider,
    SearchHit,
    FetchedPage,
    Provider,
)
from .service import JobIntel


async def read_job_url(url, **kwargs):
    return await JobIntel(**kwargs).read_job_url(url)


async def sample_jobs(direction, *, on_progress=None, **kwargs):
    return await JobIntel(**kwargs).sample_jobs(direction, on_progress=on_progress)


async def search_company(name, **kwargs):
    return await JobIntel(**kwargs).search_company(name)


__all__ = [
    "JobIntel",
    "DeepSeekProvider",
    "TavilyProvider",
    "SearchHit",
    "FetchedPage",
    "Provider",
    "read_job_url",
    "sample_jobs",
    "search_company",
]
