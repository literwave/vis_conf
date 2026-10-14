import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import (
    build_export_archive,
    insert_row_copy,
    load_table,
    move_row,
    new_configuration_table_bytes,
    prepare_export_files,
)


class BuildExportArchiveTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
