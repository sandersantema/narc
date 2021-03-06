from inspect import getmembers, isfunction
from math import inf
from os.path import exists, join
from typing import Any, Callable, Dict, Iterator, Optional, Sequence, Tuple

from ..clients import around, buffers, lsp, paths, tmux, tree_sitter
from ..shared.consts import load_hierarchy, module_entry_point, settings_json
from ..shared.da import load_json, load_module, merge_all
from ..shared.types import Factory, Seed, SnippetEngineFactory, SnippetSeed
from .types import (
    CacheOptions,
    CacheSpec,
    DisplayOptions,
    EngineFactory,
    MatchOptions,
    Settings,
    SnippetEngineSpec,
    SourceFactory,
    SourceSpec,
)


def load_source(config: Dict[str, Any]) -> SourceSpec:
    cache = CacheSpec(
        enabled=config["cache"]["enabled"],
        same_filetype=config["cache"]["same_filetype"],
    )
    spec = SourceSpec(
        main=config["main"],
        enabled=config["enabled"],
        short_name=config["short_name"],
        limit=config["limit"],
        unique=config["unique"],
        cache=cache,
        rank=config["rank"],
        config=config["config"],
    )
    return spec


def load_engine(config: Dict[str, Any]) -> SnippetEngineSpec:
    spec = SnippetEngineSpec(
        main=config["main"],
        enabled=config["enabled"],
        kinds=config["kinds"],
        config=config.get("config") or {},
    )
    return spec


def initial(configs: Sequence[Any]) -> Settings:
    config = merge_all(load_json(settings_json), *configs, replace=True)
    display_o = config["display"]
    match_o = config["match"]
    cache_o = config["cache"]
    display = DisplayOptions(
        ellipsis=display_o["ellipsis"],
        tabsize=display_o["tabsize"],
        pum_max_len=display_o["pum_max_len"],
    )
    match = MatchOptions(
        transpose_band=match_o["transpose_band"],
        unifying_chars={*match_o["unifying_chars"]},
    )
    cache = CacheOptions(
        prefix_matches=cache_o["prefix_matches"],
        short_name=cache_o["short_name"],
        source_name=cache_o["source_name"],
        limit=cache_o["limit"],
        rank_penalty=cache_o["rank_penalty"],
    )
    sources = {name: load_source(conf) for name, conf in config["sources"].items()}
    snippet_engines = {
        name: load_engine(conf) for name, conf in config["snippet_engines"].items()
    }
    settings = Settings(
        retries=config["retries"],
        timeout=(config["timeout"] or inf) / 1000,
        display=display,
        match=match,
        cache=cache,
        sources=sources,
        snippet_engines=snippet_engines,
        logging_level=config["logging_level"],
    )
    return settings


def load_external(main_name: str) -> Optional[Callable[..., Any]]:
    for path in load_hierarchy:
        candidate = join(path, main_name)
        if exists(candidate):
            mod = load_module(candidate)
            for member_name, func in getmembers(mod, isfunction):
                if member_name == module_entry_point:
                    return func
    return None


def assemble(spec: SourceSpec, main: Factory, match: MatchOptions) -> SourceFactory:
    limit = spec.limit or inf
    rank = spec.rank or 100
    config = spec.config
    seed = Seed(match=match, limit=limit, config=config,)
    fact = SourceFactory(
        enabled=spec.enabled,
        short_name=spec.short_name,
        limit=limit,
        unique=spec.unique,
        cache=spec.cache,
        rank=rank,
        seed=seed,
        manufacture=main,
    )
    return fact


def load_factories(settings: Settings) -> Dict[str, SourceFactory]:
    def cont() -> Iterator[Tuple[str, SourceFactory]]:
        intrinsic: Dict[str, Factory] = {
            around.NAME: around.main,
            buffers.NAME: buffers.main,
            lsp.NAME: lsp.main,
            paths.NAME: paths.main,
            tmux.NAME: tmux.main,
            tree_sitter.NAME: tree_sitter.main,
        }

        for name, main in intrinsic.items():
            spec = settings.sources[name]
            yield name, assemble(spec, main=main, match=settings.match)

        for name, spec in settings.sources.items():
            if name not in intrinsic:
                spec = settings.sources[name]
                main = load_external(spec.main)
                if main:
                    yield name, assemble(spec, main=main, match=settings.match)

    return {name: main for name, main in cont()}


def build(
    spec: SnippetEngineSpec, main: SnippetEngineFactory, match: MatchOptions
) -> EngineFactory:
    seed = SnippetSeed(config=spec.config, match=match)
    fact = EngineFactory(seed=seed, manufacture=main)
    return fact


def load_engines(settings: Settings) -> Dict[str, EngineFactory]:
    def cont() -> Iterator[Tuple[Sequence[str], EngineFactory]]:
        intrinsic: Dict[str, SnippetEngineFactory] = {}

        for name, main in intrinsic.items():
            spec = settings.snippet_engines[name]
            yield spec.kinds, build(spec, main=main, match=settings.match)

        for name, spec in settings.snippet_engines.items():
            if name not in intrinsic:
                spec = settings.snippet_engines[name]
                main = load_external(spec.main)
                if main:
                    yield spec.kinds, build(spec, main=main, match=settings.match)

    return {name: main for names, main in cont() for name in names}
