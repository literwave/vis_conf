import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import (
    build_export_archive,
    export_json_data,
    export_lua,
    insert_row_copy,
    load_table,
    move_row,
    new_configuration_table_bytes,
    prepare_export_files,
)
from export_data import checked_export_directory, remove_stale_export_files
from table_file import parse_data_value


class BuildExportArchiveTests(unittest.TestCase):
    def test_json_export_omits_null_fields_and_array_items(self):
        exported = export_json_data(
            ["id", "optional", "details"],
            ["integer", "string", "json"],
            [
                {
                    "id": 1,
                    "optional": None,
                    "details": '{"skip": null, "items": [null, 2, {"skip": null, "keep": true}]}',
                }
            ],
            key_columns=["id"],
        )

        self.assertEqual(
            json.loads(exported),
            {"1": {"id": 1, "details": {"items": [2, {"keep": True}]}}},
        )

    def test_lua_export_omits_null_fields_and_array_items(self):
        exported = export_lua(
            ["id", "optional", "details"],
            ["integer", "string", "lua_object"],
            [
                {
                    "id": 1,
                    "optional": None,
                    "details": "{ skip = nil, items = { nil, 2, { skip = nil, keep = true } } }",
                }
            ],
            key_columns=["id"],
        ).decode("utf-8")

        self.assertNotIn("nil", exported)
        self.assertIn('["items"] = {\n                2,', exported)
        self.assertIn('["keep"] = true', exported)

    def test_rows_can_be_reordered_and_copied_without_sharing_nested_values(self):
        rows = [
            {"id": 1, "meta": {"tags": ["old"]}},
            {"id": 2, "meta": {"tags": []}},
        ]

        move_row(rows, 1, 0)
        copied_index = insert_row_copy(rows, rows[0], 1)
        rows[copied_index]["meta"]["tags"].append("copy")

        self.assertEqual([row["id"] for row in rows], [2, 2, 1])
        self.assertEqual(rows[0]["meta"]["tags"], [])
        self.assertEqual(rows[1]["meta"]["tags"], ["copy"])

    def test_row_move_rejects_out_of_range_indices(self):
        with self.assertRaises(IndexError):
            move_row([{"id": 1}], 0, 1)

    def test_new_configuration_table_starts_with_default_id_column(self):
        columns, types, targets, annotations, rows = load_table(
            Path("new_table.tsv"),
            file_bytes=new_configuration_table_bytes(),
        )

        self.assertEqual(columns, ["id"])
        self.assertEqual(types, ["integer"])
        self.assertEqual(targets, ["both"])
        self.assertEqual(annotations, ["唯一标识"])
        self.assertEqual(rows, [])

    def test_archive_keeps_frontend_and_backend_folders(self):
        archive_bytes = build_export_archive(
            [
                (Path("backend/items.lua"), b"return {}"),
                (Path("frontend/items.json"), b"[]"),
            ]
        )

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            self.assertEqual(
                archive.namelist(),
                ["backend/items.lua", "frontend/items.json"],
            )
            self.assertEqual(archive.read("backend/items.lua"), b"return {}")
            self.assertEqual(archive.read("frontend/items.json"), b"[]")

    def test_archive_rejects_paths_outside_export_targets(self):
        with self.assertRaisesRegex(ValueError, "无效的导出端目录"):
            build_export_archive([(Path("other/items.json"), b"[]")])

    def test_archive_rejects_duplicate_output_names(self):
        with self.assertRaisesRegex(ValueError, "ZIP 中存在重复文件"):
            build_export_archive(
                [
                    (Path("backend/items.lua"), b"first"),
                    (Path("backend/items.lua"), b"second"),
                ]
            )

    def test_mobile_export_accepts_selected_tsv_bytes_without_directories(self):
        source = (
            "id\tname\n"
            "integer\tstring\n"
            "both\tboth\n"
            "ID\tName\n"
            "1\tPotion\n"
        ).encode("utf-8")
        columns, data_types, targets, _, rows = load_table(
            Path("mobile-files/items.tsv"),
            file_bytes=source,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            backend_directory = str(Path(temporary_directory) / "backend")
            frontend_directory = str(Path(temporary_directory) / "frontend")
            outputs = prepare_export_files(
                columns=columns,
                data_types=data_types,
                targets=targets,
                rows=rows,
                source_name="items.tsv",
                backend_format="lua",
                frontend_format="json",
                backend_directory=backend_directory,
                frontend_directory=frontend_directory,
                key_columns=["id"],
                validate_directories=False,
            )

        archive_bytes = build_export_archive(outputs)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"backend/items.lua", "frontend/items.json"},
            )

    def test_export_key_conflict_identifies_fields_and_conflicting_values(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(
                ValueError,
                r"第 2 行与第 1 行的 key 组合重复或层级冲突"
                r"（id=1003）.*key 字段是否重复",
            ):
                prepare_export_files(
                    columns=["id", "name"],
                    data_types=["integer", "string"],
                    targets=["both", "both"],
                    rows=[
                        {"id": 1003, "name": "First"},
                        {"id": 1003, "name": "Second"},
                    ],
                    source_name="game_config.tsv",
                    backend_format="lua",
                    frontend_format="json",
                    backend_directory=temporary_directory,
                    frontend_directory=temporary_directory,
                    key_columns=["id"],
                    validate_directories=False,
                )


    def test_lua_array_rejects_a_dictionary_with_a_specific_reason(self):
        with self.assertRaisesRegex(ValueError, "当前类型是 Lua 表数组"):
            parse_data_value("{ none = 0, windows = 1 }", "lua_array")

    def test_missing_export_directory_names_the_path(self):
        missing = "D:/missing-export"
        with self.assertRaisesRegex(ValueError, f"后端导出目录不存在：{missing}"):
            checked_export_directory("后端导出目录", missing)
        self.assertIsNone(checked_export_directory("后端导出目录", "尚未选择"))

    def test_full_export_removes_files_without_a_configuration_table(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            backend = root / "backend"
            frontend = root / "frontend"
            backend.mkdir()
            frontend.mkdir()
            kept = backend / "hero.lua"
            stale = backend / "old_item.lua"
            kept.write_text("return {}", encoding="utf-8")
            stale.write_text("return {}", encoding="utf-8")
            (frontend / "old_item.json").write_text("{}", encoding="utf-8")
            (frontend / "hero.json").write_text("{}", encoding="utf-8")
            (backend / "notes.txt").write_text("keep", encoding="utf-8")

            removed = remove_stale_export_files(
                str(backend), "lua", {os.path.normcase(str(kept.resolve()))}
            )
            removed.extend(
                remove_stale_export_files(
                    str(frontend),
                    "json",
                    {os.path.normcase(str((frontend / "hero.json").resolve()))},
                )
            )

            self.assertEqual({path.name for path in removed}, {"old_item.lua", "old_item.json"})
            self.assertTrue(kept.is_file())
            self.assertTrue((frontend / "hero.json").is_file())
            self.assertTrue((backend / "notes.txt").is_file())
            self.assertFalse(stale.exists())
            self.assertFalse((frontend / "old_item.json").exists())


if __name__ == "__main__":
    unittest.main()
