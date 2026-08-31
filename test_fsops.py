"""
test_fsops.py — тесты ядра файловых операций.

Запуск:
    python test_fsops.py
"""

import json
import os
import sys
import tempfile
import unittest

from fsops import FileSystemOps, FSError


class TestFileSystemOps(unittest.TestCase):
    """Полный набор тестов для FileSystemOps."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fs = FileSystemOps(root=self.tmpdir)

    def _path(self, *parts):
        return os.path.join(self.tmpdir, *parts)

    # --- Базовые операции ---

    def test_list_directory_empty(self):
        result = json.loads(self.fs.list_directory(""))
        self.assertEqual(result["items"], [])

    def test_create_directory(self):
        msg = self.fs.create_directory("testdir")
        self.assertIn("Папка готова", msg)
        self.assertTrue(os.path.isdir(self._path("testdir")))

    def test_create_nested_directory(self):
        self.fs.create_directory("a/b/c")
        self.assertTrue(os.path.isdir(self._path("a", "b", "c")))

    def test_write_and_read_file(self):
        self.fs.write_file("hello.txt", "Hello, World!")
        content = self.fs.read_file("hello.txt")
        self.assertEqual(content, "Hello, World!")

    def test_write_file_creates_intermediate_dirs(self):
        self.fs.write_file("deep/nested/file.txt", "content")
        self.assertTrue(os.path.isfile(self._path("deep", "nested", "file.txt")))

    def test_read_file_not_found(self):
        with self.assertRaises(FSError):
            self.fs.read_file("nonexistent.txt")

    def test_read_file_is_directory(self):
        self.fs.create_directory("mydir")
        with self.assertRaises(FSError):
            self.fs.read_file("mydir")

    def test_read_multiple_files(self):
        self.fs.write_file("a.txt", "AAA")
        self.fs.write_file("b.txt", "BBB")
        result = json.loads(self.fs.read_multiple_files(["a.txt", "b.txt"]))
        self.assertEqual(result["a.txt"], "AAA")
        self.assertEqual(result["b.txt"], "BBB")

    def test_read_multiple_files_with_error(self):
        result = json.loads(self.fs.read_multiple_files(["exists.txt", "missing.txt"]))
        self.assertIn("ошибка", result["missing.txt"])

    # --- Редактирование ---

    def test_edit_file_replace_first(self):
        self.fs.write_file("edit.txt", "foo bar baz")
        msg = self.fs.edit_file("edit.txt", "foo", "xxx", replace_all=False)
        self.assertIn("Заменено вхождений: 1", msg)
        self.assertEqual(self.fs.read_file("edit.txt"), "xxx bar baz")

    def test_edit_file_replace_all(self):
        self.fs.write_file("edit.txt", "foo bar foo")
        msg = self.fs.edit_file("edit.txt", "foo", "baz", replace_all=True)
        self.assertIn("Заменено вхождений: 2", msg)
        self.assertEqual(self.fs.read_file("edit.txt"), "baz bar baz")

    def test_edit_file_not_found(self):
        self.fs.write_file("edit.txt", "hello")
        with self.assertRaises(FSError):
            self.fs.edit_file("edit.txt", "zzz", "xxx")

    def test_edit_file_ambiguous(self):
        self.fs.write_file("edit.txt", "foo foo")
        with self.assertRaises(FSError):
            self.fs.edit_file("edit.txt", "foo", "bar", replace_all=False)

    # --- Перемещение и удаление ---

    def test_move_file(self):
        self.fs.write_file("src.txt", "move me")
        self.fs.move_file("src.txt", "dst.txt")
        self.assertFalse(os.path.isfile(self._path("src.txt")))
        self.assertTrue(os.path.isfile(self._path("dst.txt")))
        self.assertEqual(self.fs.read_file("dst.txt"), "move me")

    def test_move_file_to_subdirectory(self):
        self.fs.write_file("src.txt", "data")
        self.fs.create_directory("sub")
        self.fs.move_file("src.txt", "sub/src.txt")
        self.assertTrue(os.path.isfile(self._path("sub", "src.txt")))

    def test_delete_file(self):
        self.fs.write_file("temp.txt", "delete me")
        msg = self.fs.delete_file("temp.txt")
        self.assertIn("Файл удалён", msg)
        self.assertFalse(os.path.isfile(self._path("temp.txt")))

    def test_delete_directory(self):
        self.fs.create_directory("mydir")
        self.fs.write_file("mydir/file.txt", "inside")
        msg = self.fs.delete_file("mydir")
        self.assertIn("Папка удалена", msg)
        self.assertFalse(os.path.isdir(self._path("mydir")))

    def test_delete_root_fails(self):
        with self.assertRaises(FSError):
            self.fs.delete_file("")

    def test_delete_nonexistent_fails(self):
        with self.assertRaises(FSError):
            self.fs.delete_file("ghost")

    # --- Поиск ---

    def test_search_files(self):
        self.fs.write_file("script.py", "code")
        self.fs.write_file("readme.md", "docs")
        self.fs.write_file("data.json", "{}")
        result = json.loads(self.fs.search_files("*.py"))
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["results"][0]["path"].endswith("script.py"))

    def test_search_files_recursive_glob(self):
        self.fs.create_directory("sub")
        self.fs.write_file("sub/nested.py", "code")
        result = json.loads(self.fs.search_files("**/*.py"))
        self.assertEqual(result["count"], 1)

    def test_search_files_no_match(self):
        result = json.loads(self.fs.search_files("*.xyz"))
        self.assertEqual(result["count"], 0)

    # --- Информация ---

    def test_get_file_info(self):
        self.fs.write_file("info.txt", "data")
        info = json.loads(self.fs.get_file_info("info.txt"))
        self.assertEqual(info["type"], "file")
        self.assertEqual(info["size_human"], "4.0 B")

    def test_get_directory_info(self):
        self.fs.create_directory("infodir")
        info = json.loads(self.fs.get_file_info("infodir"))
        self.assertEqual(info["type"], "directory")

    def test_get_file_info_not_found(self):
        with self.assertRaises(FSError):
            self.fs.get_file_info("noway")

    # --- Path traversal protection ---

    def test_traversal_absolute(self):
        with self.assertRaises(FSError):
            self.fs.read_file("/etc/passwd")

    def test_traversal_double_dot(self):
        with self.assertRaises(FSError):
            self.fs.read_file("../../etc/passwd")

    def test_traversal_symlink(self):
        import subprocess
        outside = os.path.join(os.path.dirname(self.tmpdir), "outside.txt")
        try:
            with open(outside, "w") as f:
                f.write("secret")
            link = os.path.join(self.tmpdir, "evil_link")
            os.symlink(outside, link)
            with self.assertRaises(FSError):
                self.fs.read_file("evil_link")
        finally:
            if os.path.exists(outside):
                os.unlink(outside)

    # --- Read-only mode ---

    def test_read_only_blocks_write(self):
        ro_fs = FileSystemOps(root=self.tmpdir, read_only=True)
        with self.assertRaises(FSError):
            ro_fs.write_file("x.txt", "data")

    def test_read_only_blocks_delete(self):
        self.fs.write_file("x.txt", "data")
        ro_fs = FileSystemOps(root=self.tmpdir, read_only=True)
        with self.assertRaises(FSError):
            ro_fs.delete_file("x.txt")

    def test_read_only_blocks_edit(self):
        self.fs.write_file("x.txt", "hello")
        ro_fs = FileSystemOps(root=self.tmpdir, read_only=True)
        with self.assertRaises(FSError):
            ro_fs.edit_file("x.txt", "hello", "world")

    def test_read_only_allows_read(self):
        self.fs.write_file("x.txt", "data")
        ro_fs = FileSystemOps(root=self.tmpdir, read_only=True)
        content = ro_fs.read_file("x.txt")
        self.assertEqual(content, "data")


if __name__ == "__main__":
    unittest.main()