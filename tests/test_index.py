from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis.config import Config, Source, load_config
from personal_asis.index import Index, group_replicas


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.note = self.base / "Note"
        self.daily = self.base / "Daily"
        self.note.mkdir()
        self.daily.mkdir()
        self.config = Config("mac", (
            Source("note", self.note, "normal", True, True, ("Health",)),
            Source("daily", self.daily, "private", True, False, ()),
        ))
        self.dbpath = self.base / "runtime" / "index.sqlite3"
        self.index = Index(self.dbpath, self.config)
        self.addCleanup(self.index.db.close)

    def write(self, name="a.md", text="# 系统笔记\n深度学习 inference engine #tag\n"):
        path = self.note / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def hits(self, query, channel="local"):
        result = self.index.search(query, channel)
        return [hit for group in result["results"] for hit in group["replicas"]]

    def test_lifecycle_preserves_identity_and_versions(self):
        path = self.write()
        self.assertEqual(self.index.reconcile()["added"], 1)
        old = self.hits("inference")[0]
        path.write_text("# Systems\nGPU inference changes\n", encoding="utf-8")
        self.assertEqual(self.index.reconcile()["modified"], 1)
        new = self.hits("inference")[0]
        self.assertEqual(old["document_id"], new["document_id"])
        self.assertNotEqual(old["content_hash"], new["content_hash"])
        self.assertEqual(self.index.db.execute("SELECT count(*) FROM versions").fetchone()[0], 2)
        path.unlink()
        self.assertEqual(self.index.reconcile()["deleted"], 1)
        self.assertEqual(self.hits("inference"), [])
        self.write(text="# Replacement\ninference\n")
        self.index.reconcile()
        self.assertNotEqual(new["document_id"], self.hits("inference")[0]["document_id"])

    def test_private_metadata_permission_is_source_scoped_and_does_not_share_body(self):
        life = self.base / "Life"
        life.mkdir()
        (life / "record.md").write_text("---\nsensitivity: private\n---\n# 合成生活记录\n合成 LIFE_BODY_SENTINEL\n")
        (self.daily / "record.md").write_text("# 合成旧日记\n合成 OLD_DAILY_SENTINEL\n")
        self.write(text="---\nsensitivity: private\n---\n# 合成普通来源私密条目\n合成 STUDY_PRIVATE_SENTINEL\n")
        self.index.config = replace(self.config, sources=(*self.config.sources,
            Source("life", life, "private", True, True, (), private_remote_metadata=True)))
        self.index.reconcile()
        for channel in ("feishu", "pwa"):
            hits = self.hits("合成", channel)
            self.assertEqual({h["source_id"] for h in hits}, {"life"})
            self.assertNotIn("LIFE_BODY_SENTINEL", json.dumps(hits))
            self.assertNotIn("excerpt", json.dumps(hits))
            self.assertNotIn("original_uri", json.dumps(hits))
        local = self.hits("LIFE_BODY_SENTINEL")[0]
        self.assertEqual(local["policy"], "private")
        self.assertEqual({h["source_id"] for h in self.index.catalog()["documents"]}, {"life"})
        self.index.config = replace(self.index.config, sources=tuple(
            replace(s, private_remote_metadata=False) if s.id == "life" else s for s in self.index.config.sources))
        self.assertEqual(self.hits("合成", "pwa"), [])

    def test_metadata_first_avoids_hashing_unchanged(self):
        self.write()
        self.index.reconcile()
        with patch.object(Index, "_read", side_effect=AssertionError("should not hash")):
            report = self.index.reconcile()
        self.assertEqual(report["unchanged"], 1)
        self.assertEqual(report["hashes_computed"], 0)
        self.assertEqual(self.index.reconcile(force=True)["hashes_computed"], 1)

    def test_rename_and_move_preserve_identity(self):
        path = self.write()
        self.index.reconcile()
        identity = self.hits("inference")[0]["document_id"]
        (self.note / "sub").mkdir()
        path.rename(self.note / "sub" / "b.md")
        report = self.index.reconcile()
        self.assertEqual(report["moved"], 1)
        hit = self.hits("inference")[0]
        self.assertEqual(hit["document_id"], identity)
        self.assertEqual(hit["path_hint"], "sub/b.md")

    def test_copy_does_not_guess_identity(self):
        path = self.write()
        self.index.reconcile()
        identity = self.hits("inference")[0]["document_id"]
        self.write("b.md", path.read_text())
        path.unlink()
        report = self.index.reconcile()
        self.assertEqual(report["moved"], 0)
        self.assertEqual(report["deleted"], 1)
        self.assertNotEqual(identity, self.hits("inference")[0]["document_id"])

    def test_path_swap_follows_document_inodes(self):
        a = self.write("a.md", "alpha evidence\n")
        b = self.write("b.md", "beta evidence\n")
        self.index.reconcile()
        identity = self.hits("alpha")[0]["document_id"]
        a.rename(self.note / "temp.md")
        b.rename(a)
        (self.note / "temp.md").rename(b)
        report = self.index.reconcile()
        self.assertEqual(report["moved"], 2)
        hit = self.hits("alpha")[0]
        self.assertEqual(hit["document_id"], identity)
        self.assertEqual(hit["path_hint"], "b.md")

    def test_rename_overwrite_removes_replaced_document(self):
        a = self.write("a.md", "alpha evidence\n")
        b = self.write("b.md", "beta evidence\n")
        self.index.reconcile()
        identity = self.hits("beta")[0]["document_id"]
        b.replace(a)
        report = self.index.reconcile()
        self.assertEqual(report["moved"], 1)
        self.assertEqual(report["deleted"], 1)
        self.assertEqual(self.hits("alpha"), [])
        self.assertEqual(self.hits("beta")[0]["document_id"], identity)

    def test_move_and_replacement_at_old_path_keep_distinct_identity(self):
        a = self.write("a.md", "alpha evidence\n")
        self.index.reconcile()
        identity = self.hits("alpha")[0]["document_id"]
        a.rename(self.note / "b.md")
        self.write("a.md", "replacement evidence\n")
        report = self.index.reconcile()
        self.assertEqual(report["moved"], 1)
        self.assertEqual(report["added"], 1)
        self.assertEqual(self.hits("alpha")[0]["document_id"], identity)
        self.assertNotEqual(self.hits("replacement")[0]["document_id"], identity)

    def test_replicas_group_without_merging_uuid(self):
        self.write()
        self.write("b.md")
        self.index.reconcile()
        groups = self.index.search("inference")["results"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["replicas"]), 2)
        self.assertEqual(len({h["document_id"] for h in groups[0]["replicas"]}), 2)
        other = {**groups[0]["replicas"][0], "node_id": "rog", "document_id": "another-uuid"}
        self.assertEqual(len(group_replicas([groups[0]["replicas"][0], other])[0]["replicas"]), 2)

    def test_chinese_short_terms_and_safe_literal_query(self):
        self.write(text="# 系统\n深度学习与芯片\nC++ AND 100%\n")
        self.index.reconcile()
        for query in ("深度学习", "芯片", "芯", "C++", "AND", "100%", "学习 芯片"):
            self.assertEqual(len(self.hits(query)), 1, query)
        self.assertEqual(self.hits("学习 不存在"), [])
        self.assertEqual(self.hits('" OR "'), [])
        with self.assertRaises(ValueError):
            self.index.search(" ")

    def test_frontmatter_links_tags_and_location(self):
        self.write(text='---\ntitle: "自定义标题"\ntags: [hardware]\n---\n# 别的标题\n[inference](https://example.invalid) ![[chip.png]] #GPU\n')
        self.index.reconcile()
        hit = self.hits("inference")[0]
        self.assertEqual(hit["title"], "自定义标题")
        self.assertEqual(hit["line_start"], 6)
        self.assertTrue(hit["original_uri"].startswith("file://"))
        self.assertEqual(len(self.hits("hardware")), 1)
        self.assertEqual(len(self.hits("chip.png")), 1)

    def test_private_never_leaks_title_path_or_excerpt(self):
        self.write(text="# Public\ninference\n")
        (self.daily / "secret.md").write_text("# Private diary\ninference secret\n")
        self.write("flagged.md", "---\nsensitivity: private\n---\n# Private in Note\ninference sensitive\n")
        self.index.reconcile()
        self.assertEqual(len(self.hits("inference")), 3)
        for channel in ("pwa", "feishu"):
            hits = self.hits("inference", channel)
            self.assertEqual(len(hits), 1)
            self.assertNotIn("excerpt", hits[0])
            self.assertNotIn("original_uri", hits[0])
            data = json.dumps(hits)
            self.assertNotIn("Private", data)
            self.assertNotIn("secret.md", data)
        self.assertEqual(len(self.index.catalog()["documents"]), 1)

    def test_policy_changes_effective_without_reconcile(self):
        self.write()
        self.index.reconcile()
        restricted = replace(self.config, sources=(replace(self.config.sources[0], remote_metadata=False), self.config.sources[1]))
        with Index(self.dbpath, restricted) as second:
            self.assertEqual(second.search("inference", "feishu")["results"], [])
            self.assertEqual(second.catalog()["documents"], [])
        private = replace(self.config, sources=(replace(self.config.sources[0], policy="private", remote_metadata=False), self.config.sources[1]))
        with Index(self.dbpath, private) as second:
            hit = second.search("inference")["results"][0]["replicas"][0]
            self.assertEqual(hit["policy"], "private")

    def test_new_exclusion_immediately_removes_current_hit(self):
        self.write()
        self.index.reconcile()
        changed = replace(self.config, sources=(replace(self.config.sources[0], exclude=("a.md",)), self.config.sources[1]))
        with Index(self.dbpath, changed) as second:
            self.assertEqual(second.search("inference")["results"], [])

    def test_stale_results_suppressed_until_reconciled(self):
        path = self.write()
        self.index.reconcile()
        path.write_text("---\npolicy: private\n---\ninference new content\n")
        result = self.index.search("inference", "feishu")
        self.assertEqual(result["results"], [])
        self.assertEqual(result["stale_candidates_skipped"], 1)
        self.assertEqual(self.index.catalog()["documents"], [])
        self.index.reconcile()
        self.assertEqual(self.hits("inference", "feishu"), [])
        path.unlink()
        self.assertEqual(self.hits("inference"), [])

    def test_unavailable_source_keeps_identity_and_recovers(self):
        self.write()
        self.index.reconcile()
        identity = self.hits("inference")[0]["document_id"]
        self.note.rename(self.base / "offline")
        report = self.index.reconcile()
        self.assertEqual(report["deleted"], 0)
        self.assertEqual(report["sources"][0]["status"], "unavailable_or_unreadable")
        self.assertEqual(self.hits("inference"), [])
        (self.base / "offline").rename(self.note)
        self.index.reconcile()
        self.assertEqual(self.hits("inference")[0]["document_id"], identity)

    def test_failed_candidate_read_does_not_partially_delete(self):
        first = self.write()
        self.write("b.md")
        self.index.reconcile()
        first.unlink()
        self.write("b.md", "changed\n")
        with patch.object(Index, "_read", side_effect=PermissionError):
            report = self.index.reconcile()
        self.assertEqual(report["deleted"], 0)
        self.assertEqual(self.index.db.execute("SELECT count(*) FROM documents WHERE active=1").fetchone()[0], 2)
        self.assertEqual(self.hits("inference"), [])

    def test_skips_symlinks_and_excluded_health(self):
        outside = self.base / "outside.md"
        outside.write_text("inference secret\n")
        (self.note / "link.md").symlink_to(outside)
        (self.note / "linked-dir").symlink_to(self.daily, target_is_directory=True)
        self.write("Health/secret.md", "inference secret\n")
        self.write()
        report = self.index.reconcile()
        self.assertEqual(report["added"], 1)
        self.assertEqual(len(self.hits("inference")), 1)

    def test_reader_rejects_replaced_ancestor_symlink(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("inference private\n")
        (self.note / "sub").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            Index._read(self.note / "sub" / "secret.md", root=self.note)

    def test_replaced_source_root_does_not_reuse_identity(self):
        self.write()
        self.index.reconcile()
        identity = self.hits("inference")[0]["document_id"]
        newroot = self.base / "different"
        newroot.mkdir()
        (newroot / "a.md").write_text("inference\n")
        config = replace(self.config, sources=(replace(self.config.sources[0], root=newroot), self.config.sources[1]))
        with Index(self.dbpath, config) as second:
            self.assertEqual(second.search("inference")["results"], [])
            second.reconcile()
            new = second.search("inference")["results"][0]["replicas"][0]
            self.assertNotEqual(new["document_id"], identity)

    def test_reconciliation_read_only_and_audit_minimizes_data(self):
        path = self.write()
        before = path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ctime_ns
        self.index.reconcile()
        self.hits("inference")
        after = path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ctime_ns
        self.assertEqual(before, after)
        audit = " ".join(r[0] for r in self.index.db.execute("SELECT details FROM operations"))
        self.assertNotIn("inference", audit)
        self.assertNotIn("深度学习", audit)
        self.assertNotIn("a.md", audit)
        self.assertEqual(self.dbpath.stat().st_mode & 0o777, 0o600)


class ConfigTests(unittest.TestCase):
    def test_rejects_private_remote_and_overlapping_roots(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "sources.yaml"
            source = {"id": "daily", "root": "/tmp/daily", "policy": "private", "remote_metadata": True}
            path.write_text(json.dumps({"node_id": "mac", "sources": [source]}))
            with self.assertRaises(ValueError):
                load_config(path)
            source["remote_metadata"] = False
            other = {**source, "id": "nested", "root": "/tmp/daily/nested"}
            path.write_text(json.dumps({"node_id": "mac", "sources": [source, other]}))
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
