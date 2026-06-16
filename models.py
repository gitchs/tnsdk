from __future__ import annotations

from pydantic import BaseModel
from pydantic.alias_generators import to_camel


class AutoPauseConfig(BaseModel):
    enable: bool = False

    model_config = {"alias_generator": to_camel, "populate_by_name": True}


class NodegroupConditions(BaseModel):
    engine_initialized: bool = False
    storage_active: bool = False
    resizing: bool = False
    upgrading: bool = False
    public_network_access_updating: bool = False
    vpc_network_access_updating: bool = False

    model_config = {"alias_generator": to_camel, "populate_by_name": True}


class Nodegroup(BaseModel):
    id: str
    contextlake_id: str
    catalog_id: str | None = None
    cache_id: str | None = None
    name: str
    owner: str
    creator: str
    modifier: str
    state: str
    target_state: str
    conditions: NodegroupConditions
    version: str
    target_version: str
    previous_version: str | None = None
    size: int
    target_size: int
    gmt_created: int
    gmt_modified: int
    gmt_upgraded: int | None = None
    operation_id: str | None = None
    description: str | None = None
    auto_pause_config: AutoPauseConfig

    model_config = {"alias_generator": to_camel, "populate_by_name": True}


class NodegroupList(BaseModel):
    items: list[Nodegroup]


class CatalogGeneration(BaseModel):
    id: str
    mode: str
    nodegroup_version: str

    model_config = {"alias_generator": to_camel, "populate_by_name": True}


class Catalog(BaseModel):
    id: str
    contextlake_id: str
    name: str
    state: str
    owner: str
    creator: str
    modifier: str
    gmt_created: int
    gmt_modified: int
    description: str | None = None
    current_generation_id: str
    generations: list[CatalogGeneration] = []

    model_config = {"alias_generator": to_camel, "populate_by_name": True}


class CatalogList(BaseModel):
    page_num: int
    page_size: int
    total_size: int
    total_pages: int
    items: list[Catalog]

    model_config = {"alias_generator": to_camel, "populate_by_name": True}
