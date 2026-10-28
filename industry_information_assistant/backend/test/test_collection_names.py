import ast
import hashlib
from pathlib import Path
import re
import runpy
import unittest
from typing import Dict, Any

SERVICE = Path(__file__).resolve().parents[1] / "app/service"
names = runpy.run_path(str(SERVICE / "collection_names.py"))


class CollectionNameTests(unittest.TestCase):
    def test_unicode_punctuation_and_long_names_are_valid_and_stable(self):
        for name in ("解剖学", "心脏病学", "Anatomy / Notes", "a-b", "a_b", "😀", "x" * 255):
            with self.subTest(name=name[:20]):
                result = names["knowledge_collection_name"](name)
                self.assertRegex(result, r"^[A-Za-z_][A-Za-z0-9_]*$")
                self.assertLessEqual(len(result), 128)
                self.assertEqual(result, names["knowledge_collection_name"](name))
                self.assertEqual(result, names["normalize_collection_name"](result))
        self.assertNotEqual(names["knowledge_collection_name"]("解剖学"), names["knowledge_collection_name"]("病理学"))
        self.assertNotEqual(names["knowledge_collection_name"]("a-b"), names["knowledge_collection_name"]("a/b"))

    def test_existing_english_collection_is_unchanged(self):
        self.assertEqual(names["knowledge_collection_name"]("Medical Notes"), "kb_medical_notes")

    def pipeline(self, storage_fails=False):
        tree = ast.parse((SERVICE / "docmind_service.py").read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "process_document_with_docmind")
        calls = []
        class Storage:
            def create_collection(self, name):
                calls.append(("create", name))
                if storage_fails:
                    raise RuntimeError("storage unavailable")
            def insert_documents(self, name, documents):
                calls.append(("insert", name, documents))
        class Parser:
            def __init__(self): calls.append(("parser",))
            def submit_job(self, *args): return "test-job"
            def wait_for_completion(self, *args): return True
            def collect_all_results(self, *args): return "synthetic test text"
        scope = dict(Dict=Dict, Any=Any, hashlib=hashlib, normalize_collection_name=names["normalize_collection_name"],
                     get_milvus_service=lambda: Storage(), DocMindService=Parser,
                     chunk_text=lambda *args, **kwargs: ["synthetic test text"],
                     generate_embedding=lambda *args: [[1.0, 0.0]])
        exec(compile(ast.Module(body=[function], type_ignores=[]), "docmind_service.py", "exec"), scope)
        return scope["process_document_with_docmind"]("unused.pdf", "测试.pdf", "kb_解剖学"), calls

    def test_storage_preflight_precedes_paid_parser_and_insert_uses_same_name(self):
        result, calls = self.pipeline()
        self.assertTrue(result["success"])
        self.assertEqual(calls[0][0], "create")
        self.assertEqual(calls[1][0], "parser")
        self.assertEqual(calls[0][1], calls[-1][1])
        self.assertEqual(calls[-1][2][0]["kb_id"], calls[0][1])

    def test_storage_failure_does_not_submit_parser_or_embedding(self):
        result, calls = self.pipeline(storage_fails=True)
        self.assertFalse(result["success"])
        self.assertEqual([call[0] for call in calls], ["create"])


if __name__ == "__main__":
    unittest.main()
