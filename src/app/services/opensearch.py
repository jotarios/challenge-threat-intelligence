import asyncio
import logging
from typing import Any

from opensearchpy import (
    AsyncOpenSearch,
    ConnectionError,
    ConnectionTimeout,
    NotFoundError,
    RequestError,
    TransportError,
)

from app.models.indicators import IndicatorDetail, IndicatorSearchItem, SearchParams
from app.sanitize import escape_opensearch_wildcard

logger = logging.getLogger(__name__)

INDEX_NAME = "indicators"


class OpenSearchService:
    def __init__(self, url: str):
        self._url = url
        self._client: AsyncOpenSearch | None = None

    async def connect(self) -> None:
        for attempt in range(3):
            try:
                self._client = AsyncOpenSearch(
                    hosts=[self._url],
                    use_ssl=False,
                    verify_certs=False,
                )
                info = await self._client.info()
                logger.info("OpenSearch connected: %s", info.get("version", {}).get("number", "unknown"))
                return
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                else:
                    logger.error("OpenSearch connection failed after 3 attempts: %s", e)
                    raise

    async def get_indicator(self, indicator_id: str) -> dict[str, Any] | None:
        if not self._client:
            return None
        try:
            result = await self._client.get(index=INDEX_NAME, id=indicator_id)
            source = result["_source"]
            detail = IndicatorDetail(**source)
            return detail.model_dump(mode="json")
        except NotFoundError:
            return None
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("OpenSearch get_indicator malformed document %s: %s", indicator_id, e)
            return None
        except (ConnectionError, ConnectionTimeout) as e:
            logger.error("OpenSearch get_indicator connection error: %s", e)
            raise
        except TransportError as e:
            logger.error("OpenSearch get_indicator transport error: %s", e)
            raise

    async def search_indicators(self, params: SearchParams) -> tuple[list[dict[str, Any]], int]:
        if not self._client:
            return [], 0

        filters: list[dict[str, Any]] = []

        if params.type:
            filters.append({"term": {"type": params.type}})

        if params.value:
            escaped = escape_opensearch_wildcard(params.value)
            filters.append({"wildcard": {"value.keyword": f"*{escaped}*"}})

        if params.threat_actor:
            filters.append(
                {
                    "nested": {
                        "path": "threat_actors",
                        "query": {"term": {"threat_actors.id": params.threat_actor}},
                    }
                }
            )

        if params.campaign:
            filters.append(
                {
                    "nested": {
                        "path": "campaigns",
                        "query": {"term": {"campaigns.id": params.campaign}},
                    }
                }
            )

        range_filter: dict[str, dict[str, str]] = {}
        if params.first_seen_after:
            range_filter.setdefault("first_seen", {})["gte"] = params.first_seen_after.isoformat()
        if params.last_seen_before:
            range_filter.setdefault("last_seen", {})["lte"] = params.last_seen_before.isoformat()
        if range_filter:
            for field, condition in range_filter.items():
                filters.append({"range": {field: condition}})

        query = {"bool": {"filter": filters}} if filters else {"match_all": {}}
        from_offset = (params.page - 1) * params.limit

        try:
            result = await self._client.search(
                index=INDEX_NAME,
                body={"query": query, "from": from_offset, "size": params.limit},
            )
        except RequestError as e:
            logger.error("OpenSearch search request error: %s", e)
            raise
        except (ConnectionError, ConnectionTimeout) as e:
            logger.error("OpenSearch search connection error: %s", e)
            raise
        except TransportError as e:
            logger.error("OpenSearch search transport error: %s", e)
            raise

        total_info = result["hits"]["total"]
        total = total_info["value"] if isinstance(total_info, dict) else int(total_info)
        items = []
        for hit in result["hits"]["hits"]:
            src = hit["_source"]
            try:
                item = IndicatorSearchItem(
                    id=src["id"],
                    type=src["type"],
                    value=src["value"],
                    confidence=src["confidence"],
                    first_seen=src.get("first_seen"),
                    campaign_count=len(src.get("campaigns", [])),
                    threat_actor_count=len(src.get("threat_actors", [])),
                )
                items.append(item.model_dump(mode="json"))
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("Skipping malformed search result: %s", e)
                continue

        return items, total

    async def check_health(self) -> bool:
        if not self._client:
            return False
        try:
            await self._client.cluster.health()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.close()
