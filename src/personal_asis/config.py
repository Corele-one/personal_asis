"""Local-only configuration. JSON syntax is a strict subset of YAML 1.2."""

from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path


DEFAULT_HOME = Path.home() / "Library" / "Application Support" / "PersonalAsis"


@dataclass(frozen=True)
class Source:
    id: str
    root: Path
    policy: str
    index: bool
    remote_metadata: bool
    exclude: tuple[str, ...]
    private_remote_metadata: bool = False

    def shares_metadata(self, private: bool) -> bool:
        return self.remote_metadata and (not private or self.private_remote_metadata)

    def excludes(self, relative: str) -> bool:
        path = Path(relative)
        # A directory pattern also excludes every descendant.
        candidates = [path.as_posix(), *(p.as_posix() for p in path.parents if str(p) != ".")]
        return any(fnmatch.fnmatchcase(candidate, pattern)
                   for candidate in candidates for pattern in self.exclude)


@dataclass(frozen=True)
class Config:
    node_id: str
    sources: tuple[Source, ...]


def load_config(path: Path) -> Config:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("sources.yaml 须使用 JSON 兼容的 YAML 1.2 语法，参见配置样例") from exc
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
        for key in ("index", "remote_metadata", "private_remote_metadata"):
            if type(item.get(key, False)) is not bool:
                raise ValueError(f"{key} 必须是布尔值")
        if (policy == "private" and item.get("remote_metadata", False)
                and not item.get("private_remote_metadata", False)):
            raise ValueError("private 来源远程元数据需要单独、明确的 private_remote_metadata 许可")
        excludes = item.get("exclude", [])
        if not isinstance(excludes, list) or not all(isinstance(x, str) for x in excludes):
            raise ValueError("exclude 必须是字符串数组")
        sources.append(Source(sid, root, policy, item.get("index", True),
                              item.get("remote_metadata", False), tuple(excludes),
                              item.get("private_remote_metadata", False)))
    if not sources:
        raise ValueError("至少配置一个来源")
    # Overlapping roots could bypass a private source's classification.
    for i, source in enumerate(sources):
        for other in sources[i + 1:]:
            a, b = source.root.resolve(), other.root.resolve()
            if a == b or a in b.parents or b in a.parents:
                raise ValueError("来源 root 不得重叠；请配置互不重叠的目录，并维护排除规则")
    return Config(node, tuple(sources))
