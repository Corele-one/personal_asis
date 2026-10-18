"""Local-only configuration. JSON syntax is a strict subset of YAML 1.2."""

from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import sys

from .extractors import FORMATS
from .data_policy import credential_path


DEFAULT_HOME = (Path.home() / "Library" / "Application Support" / "PersonalAsis"
                if sys.platform == "darwin" else
                Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "personal-asis")


@dataclass(frozen=True)
class Source:
    id: str
    root: Path
    policy: str
    index: bool
    remote_metadata: bool
    exclude: tuple[str, ...]
    private_remote_metadata: bool = False
    private_paths: tuple[str, ...] = ()
    remote_metadata_paths: tuple[str, ...] | None = None
    formats: tuple[str, ...] = ("md",)
    remote_evidence: bool = False
    model_providers: tuple[str, ...] = ()
    model_paths: tuple[str, ...] = ()
    private_model_providers: tuple[str, ...] = ()
    model_all_files: bool = False
    private_remote_evidence: bool = False
    reading_cache: bool = False

    def allows_model(self, provider: str, private: bool, relative: str) -> bool:
        return (self.index and (not (private or self.policy == 'private')
                               or provider in self.private_model_providers)
                and not self.excludes(relative) and provider in self.model_providers
                and (self.model_all_files or relative in self.model_paths))

    def shares_metadata(self, private: bool, relative: str = "") -> bool:
        return (self.remote_metadata and (not private or self.private_remote_metadata)
                and (self.remote_metadata_paths is None or self._matches(relative, self.remote_metadata_paths)))

    def allows_remote_evidence(self, private: bool, relative: str) -> bool:
        return (self.remote_evidence and (not private or self.private_remote_evidence)
                and self.shares_metadata(private,relative) and not self.excludes(relative))

    @staticmethod
    def _matches(relative: str, patterns: tuple[str, ...]) -> bool:
        path = Path(relative)
        # A directory pattern also excludes every descendant.
        candidates = [path.as_posix(), *(p.as_posix() for p in path.parents if str(p) != ".")]
        return any(fnmatch.fnmatchcase(candidate, pattern)
                   for candidate in candidates for pattern in patterns)

    def excludes(self, relative: str) -> bool:
        return credential_path(relative) or self._matches(relative, self.exclude)

    def is_private_path(self, relative: str) -> bool:
        return self._matches(relative, self.private_paths)


@dataclass(frozen=True)
class Config:
    node_id: str
    sources: tuple[Source, ...]


def load_config(path: Path) -> Config:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("sources.yaml 须使用 JSON 兼容的 YAML 1.2 语法，参见配置样例") from exc
    return parse_config(data)


def root_identity(root):
    return hashlib.sha256(str(Path(root).expanduser().resolve()).encode()).hexdigest()


def load_pa1_config(home: Path) -> Config:
    """PA1 grants are separate from the production PA0 source configuration."""
    path=Path(home)/'pa1-policy.json'
    if not path.exists():
        return load_config(Path(home)/'sources.yaml')
    data=json.loads((Path(home)/'sources.yaml').read_text())
    policy=json.loads(path.read_text())
    if (not isinstance(policy,dict) or set(policy)!={'version','sources'}
            or policy['version']!=1 or not isinstance(policy['sources'],dict)):
        raise ValueError('invalid_pa1_source_policy')
    fields={'model_providers','model_paths','private_model_providers','model_all_files'}
    for grant in policy['sources'].values():
        if (not isinstance(grant,dict) or set(grant)!=fields|{'root_identity'}
                or not isinstance(grant['root_identity'],str) or len(grant['root_identity'])!=64):
            raise ValueError('invalid_pa1_source_policy')
    for source in data['sources']:
        source.update(model_providers=[],model_paths=[],private_model_providers=[],model_all_files=False)
        grant=policy['sources'].get(source['id'])
        if grant and grant['root_identity']==root_identity(source['root']):
            source.update({field:grant[field] for field in fields})
    return parse_config(data)


def parse_config(data) -> Config:
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("配置必须是对象，sources 必须是数组")
    node = data.get("node_id")
    if not isinstance(node, str) or not node.strip():
        raise ValueError("node_id 必须是非空字符串")
    sources = []
    ids = set()
    for item in data.get("sources", []):
        if not isinstance(item, dict):
            raise ValueError("来源必须是对象")
        sid = item["id"]
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError("来源 id 必须非空且不重复")
        ids.add(sid)
        root = Path(item["root"]).expanduser()
        if not root.is_absolute():
            raise ValueError("来源 root 必须是绝对路径")
        policy = item["policy"]
        if policy not in {"normal", "private"}:
            raise ValueError("policy 仅支持 normal/private")
        for key in ("index", "remote_metadata", "private_remote_metadata", "remote_evidence", "model_all_files", "private_remote_evidence", "reading_cache"):
            if type(item.get(key, False)) is not bool:
                raise ValueError(f"{key} 必须是布尔值")
        if (policy == "private" and item.get("remote_metadata", False)
                and not item.get("private_remote_metadata", False)):
            raise ValueError("private 来源远程元数据需要单独、明确的 private_remote_metadata 许可")
        excludes = item.get("exclude", [])
        if not isinstance(excludes, list) or not all(isinstance(x, str) for x in excludes):
            raise ValueError("exclude 必须是字符串数组")
        for key in ("private_paths", "remote_metadata_paths", "model_providers", "model_paths", "private_model_providers"):
            if key in item and (not isinstance(item[key], list) or not all(isinstance(x, str) for x in item[key])):
                raise ValueError(f"{key} 必须是字符串数组")
        if (policy == 'private' and set(item.get('model_providers', []))
                - set(item.get('private_model_providers', []))):
            raise ValueError('private 来源云模型需要单独 private_model_providers 许可')
        if set(item.get('private_model_providers', [])) - set(item.get('model_providers', [])):
            raise ValueError('private_model_providers 必须同时具有 model_providers 许可')
        if any(not p or not p.isascii() or not all(c.isalnum() or c in "_-" for c in p)
               for p in item.get("model_providers", [])):
            raise ValueError("model_providers 须为非空提供商标识")
        if any(not p or Path(p).is_absolute() or ".." in Path(p).parts
               or Path(p).as_posix() != p or "\\" in p for p in item.get("model_paths", [])):
            raise ValueError("model_paths 须为逐文件的规范相对路径，不解释目录或 glob")
        formats = item.get("formats", ["md"])
        if (not isinstance(formats, list) or not formats or
                any(not isinstance(f, str) or f not in FORMATS for f in formats)):
            raise ValueError("formats 必须是受支持的文本格式数组")
        sources.append(Source(sid, root, policy, item.get("index", True),
                              item.get("remote_metadata", False), tuple(excludes),
                              item.get("private_remote_metadata", False),
                              tuple(item.get("private_paths", [])),
                              tuple(item["remote_metadata_paths"]) if "remote_metadata_paths" in item else None,
                              tuple(dict.fromkeys(formats)), item.get("remote_evidence", False),
                              tuple(item.get("model_providers", [])), tuple(item.get("model_paths", [])),
                              tuple(item.get('private_model_providers', [])), item.get('model_all_files',False),
                              item.get('private_remote_evidence',False), item.get('reading_cache',False)))
    if not sources:
        raise ValueError("至少配置一个来源")
    # Overlapping roots could bypass a private source's classification.
    for i, source in enumerate(sources):
        for other in sources[i + 1:]:
            a, b = source.root.resolve(), other.root.resolve()
            if a == b or a in b.parents or b in a.parents:
                raise ValueError("来源 root 不得重叠；请配置互不重叠的目录，并维护排除规则")
    return Config(node, tuple(sources))
