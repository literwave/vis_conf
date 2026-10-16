import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flet as ft

from app import main
from plugin_catalog.protocol_export import (
    ProtocolEditor,
    _export_status,
    field_type_options,
    file_matches,
    find_protocol_tools,
    message_kind,
    message_name_error,
    parse_proto,
    render_proto,
    new_proto_text,
    normalize_proto_filename,
    resolve_import_directory,
    resolve_pb_directory,
    run_protocol_export,
    type_matches,
    validate_document,
)
from plugin_host import install_plugin, list_plugin_packages, load_plugins, uninstall_plugin


class FakePage:
    def __init__(self):
        self.title = ""
        self.bgcolor = None
        self.padding = 0
        self.platform = ft.PagePlatform.WINDOWS
        self.width = 1280
        self.height = 800
        self.window = SimpleNamespace()
        self.services = []
        self.controls = []
        self.dialogs = []
        self.web = False

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        if self.dialogs:
            self.dialogs.pop()


def _write_plugin(directory: Path, name: str, source: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(source, encoding="utf-8")


def _find_tooltip(control, tooltip, seen=None):
    if seen is None:
        seen = set()
    if control is None or id(control) in seen:
        return None
    seen.add(id(control))
    if getattr(control, "tooltip", None) == tooltip:
        return control
    for child in getattr(control, "controls", None) or []:
        found = _find_tooltip(child, tooltip, seen)
        if found is not None:
            return found
    content = getattr(control, "content", None)
    if not isinstance(content, str):
        return _find_tooltip(content, tooltip, seen)
    return None


def _button_by_content(control, label, seen=None):
    if seen is None:
        seen = set()
    if control is None or id(control) in seen:
        return None
    seen.add(id(control))
    if getattr(control, "content", None) == label and hasattr(control, "on_click"):
        return control
    for child in list(getattr(control, "controls", None) or []) + list(
        getattr(control, "actions", None) or []
    ):
        found = _button_by_content(child, label, seen)
        if found is not None:
            return found
    content = getattr(control, "content", None)
    if not isinstance(content, str):
        return _button_by_content(content, label, seen)
    return None


def _controls_of_type(control, kind, seen=None):
    if seen is None:
        seen = set()
    if control is None or id(control) in seen:
        return []
    seen.add(id(control))
    found = [control] if isinstance(control, kind) else []
    for child in getattr(control, "controls", None) or []:
        found.extend(_controls_of_type(child, kind, seen))
    content = getattr(control, "content", None)
    if not isinstance(content, str):
        found.extend(_controls_of_type(content, kind, seen))
    return found


def _control_labels(control, seen=None):
    if seen is None:
        seen = set()
    if control is None or id(control) in seen:
        return []
    seen.add(id(control))
    labels = []
    for value in (
        getattr(control, "label", None),
        getattr(control, "content", None),
        getattr(control, "value", None),
    ):
        if isinstance(value, str) and value:
            labels.append(value)
    for child in getattr(control, "controls", None) or []:
        labels.extend(_control_labels(child, seen))
    content = getattr(control, "content", None)
    if not isinstance(content, str):
        labels.extend(_control_labels(content, seen))
    return labels


def _tools_tree(root: Path) -> Path:
    tools = root / "ptotools"
    (tools / "script").mkdir(parents=True)
    (tools / "proto" / "proto_desc").mkdir(parents=True)
    (tools / "script" / "extractlua.py").write_text("# lua\n", encoding="utf-8")
    (tools / "script" / "extractluapb.py").write_text("# pb\n", encoding="utf-8")
    return tools


class PluginHostTests(unittest.TestCase):
    def test_loads_plugin_actions_and_skips_files_without_register(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            _write_plugin(
                directory,
                "hello.py",
                "def register(ctx):\n"
                "    return [type('Action', (), {'label': '你好'})()]\n",
            )
            _write_plugin(directory, "note.py", "VALUE = 1\n")
            actions, errors = load_plugins(object(), [directory])

        self.assertEqual(errors, [])
        self.assertEqual([action.label for action in actions], ["你好"])

    def test_broken_plugin_does_not_block_the_others(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            _write_plugin(directory, "broken.py", "def register(ctx):\n    raise RuntimeError('坏了')\n")
            _write_plugin(
                directory,
                "ok.py",
                "def register(ctx):\n    return [type('Action', (), {'label': '还在'})()]\n",
            )
            actions, errors = load_plugins(object(), [directory])

        self.assertEqual([action.label for action in actions], ["还在"])
        self.assertEqual(len(errors), 1)
        self.assertIn("broken.py", errors[0])
        self.assertIn("坏了", errors[0])

    def test_user_plugin_replaces_bundled_plugin_with_the_same_name(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bundled = root / "bundled"
            user = root / "user"
            _write_plugin(
                bundled,
                "demo.py",
                "def register(ctx):\n    return [type('Action', (), {'label': '内置'})()]\n",
            )
            _write_plugin(
                user,
                "demo.py",
                "def register(ctx):\n    return [type('Action', (), {'label': '用户'})()]\n",
            )
            actions, errors = load_plugins(object(), [bundled, user])

        self.assertEqual(errors, [])
        self.assertEqual([action.label for action in actions], ["用户"])


class ProtocolPluginTests(unittest.TestCase):
    def test_finds_protocol_tools_from_repository_and_selected_directory(self):
        repository = Path(__file__).resolve().parents[2]
        self.assertEqual(
            find_protocol_tools([repository / "vis_conf"]),
            repository / "ptotools",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            self.assertTrue(os.path.samefile(find_protocol_tools([root / "tsv"]), tools))
            self.assertTrue(
                os.path.samefile(
                    find_protocol_tools([tools / "proto" / "proto_desc"]),
                    tools,
                )
            )
        with tempfile.TemporaryDirectory() as other_directory:
            self.assertIsNone(find_protocol_tools([other_directory]))
        with tempfile.TemporaryDirectory() as temporary_directory:
            tools = _tools_tree(Path(temporary_directory))
            shutil.rmtree(tools / "proto")
            self.assertTrue(os.path.samefile(find_protocol_tools([tools]), tools))

    def test_export_runs_existing_scripts_from_the_tools_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            tools = _tools_tree(Path(temporary_directory))
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="copied\n", stderr=""
            )
            with patch(
                "plugin_catalog.protocol_export.subprocess.run", return_value=completed
            ) as run:
                ok, message = run_protocol_export(tools)

        self.assertTrue(ok)
        self.assertIn("协议已导出", message)
        self.assertEqual(run.call_count, 2)
        first = run.call_args_list[0]
        self.assertEqual(first.kwargs["cwd"], tools)
        self.assertEqual(
            first.args[0][1],
            str(tools / "script" / "extractlua.py"),
        )
        self.assertEqual(first.args[0][2], str(tools / "proto" / "proto_desc"))

    def test_export_stops_when_protoc_reports_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            tools = _tools_tree(Path(temporary_directory))
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="Failed to generate pb for login.proto\n",
                stderr="",
            )
            with patch(
                "plugin_catalog.protocol_export.subprocess.run", return_value=completed
            ) as run:
                ok, message = run_protocol_export(tools)

        self.assertFalse(ok)
        self.assertIn("Failed to generate", message)
        self.assertEqual(run.call_count, 1)

    def test_export_status_keeps_the_summary_and_drops_the_script_log(self):
        message = "协议已导出。\npb：D:/pb\nC#：D:/outcs\n\n--- extractlua.py（退出码 0）---\nCopied login.proto\n"
        self.assertEqual(_export_status(True, message), "协议已导出。 pb：D:/pb C#：D:/outcs")
        self.assertEqual(_export_status(False, ""), "协议导出失败。")

    def test_export_copies_generated_pb_into_the_configured_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            source = root / "proto"
            source.mkdir()
            (source / "login.proto").write_text('syntax = "proto3";\n', encoding="utf-8")
            generated = root / "server" / "proto" / "pb"
            generated.mkdir(parents=True)
            (generated / "login.pb").write_bytes(b"pb-bytes")
            pb_dir = root / "custom_pb"
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="copied\n", stderr=""
            )
            with patch(
                "plugin_catalog.protocol_export.subprocess.run", return_value=completed
            ) as run:
                ok, message = run_protocol_export(tools, source, pb_dir)

            self.assertTrue(ok)
            self.assertIn(str(pb_dir), message)
            self.assertEqual((pb_dir / "login.pb").read_bytes(), b"pb-bytes")
            self.assertEqual(
                (tools / "proto" / "proto_desc" / "login.proto").read_text(encoding="utf-8"),
                'syntax = "proto3";\n',
            )
            self.assertEqual(
                run.call_args_list[0].args[0][2],
                str(tools / "proto" / "proto_desc"),
            )

    def test_saved_directories_override_the_detected_proto_folder(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            source = root / "incoming"
            pb_dir = root / "outgoing"
            source.mkdir()
            (source / "login.proto").write_text("syntax = \"proto3\";\n", encoding="utf-8")

            self.assertEqual(resolve_import_directory(tools, str(source)), source)
            self.assertEqual(resolve_pb_directory(tools, str(pb_dir)), pb_dir)
            self.assertEqual(
                resolve_pb_directory(tools, None),
                tools.parent / "server" / "proto" / "pb",
            )

    def test_directory_settings_open_from_the_gear(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            source = root / "proto"
            source.mkdir()
            dialogs = []

            class FakeContext:
                def dialog_width(self, preferred):
                    return preferred

                def dialog_height(self, preferred, margin=80):
                    return preferred

                def update(self):
                    pass

                def show_dialog(self, dialog):
                    dialogs.append(dialog)

                def notify(self, message, error=False):
                    pass

            editor = ProtocolEditor(FakeContext(), tools, source)
            editor.rebuild()
            gear = _find_tooltip(editor.dialog.title, "目录配置")
            self.assertIsNotNone(gear)
            gear.on_click(None)
            labels = _control_labels(dialogs[-1])
            self.assertIn("proto导入目录", labels)
            self.assertIn("pb导出目录", labels)
            add_proto = _find_tooltip(editor.body, "新增 proto")
            self.assertIsNotNone(add_proto)
            add_proto.on_click(None)
            self.assertIn("文件名", _control_labels(dialogs[-1]))

    def test_file_search_matches_filename_package_and_message(self):
        document = parse_proto(
            'syntax = "proto3";\n\npackage Build;\n\nmessage s2c_req_all_build_end {\n}\n'
        )
        self.assertTrue(file_matches("build.proto", document, "build"))
        self.assertTrue(file_matches("build.proto", document, "s2c_req"))
        self.assertTrue(file_matches("build.proto", document, "Build"))
        self.assertFalse(file_matches("build.proto", document, "login"))
        self.assertTrue(file_matches("login.proto", None, ""))

    def test_protocol_dropdown_filters_by_typing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            source = root / "proto"
            source.mkdir()
            (source / "build.proto").write_text(
                'syntax = "proto3";\n\npackage Build;\n\n'
                "message s2c_req_all_build_end {\n}\n"
                "message c2s_create_build {\n\tint32 bid = 1;\n}\n",
                encoding="utf-8",
            )

            class FakeContext:
                def dialog_width(self, preferred):
                    return preferred

                def dialog_height(self, preferred, margin=80):
                    return preferred

                def update(self):
                    pass

                def show_dialog(self, dialog):
                    pass

                def notify(self, message, error=False):
                    pass

            editor = ProtocolEditor(FakeContext(), tools, source)
            editor.rebuild()
            self.assertEqual(editor.message_search.hint_text, "搜索协议，回车打开")
            editor.message_query = "create"
            editor._fill_message_list()
            names = [
                control.content.controls[1].value
                for control in editor.message_list.controls
                if isinstance(getattr(control, "content", None), ft.Row)
            ]
            self.assertEqual(names, ["c2s_create_build"])
            tag = editor.message_list.controls[0].content.controls[0].content.value
            self.assertEqual(tag, "请求")
            editor.message_query = ""
            editor.message_search_focused = True
            editor._on_key(
                SimpleNamespace(
                    key="Arrow Down", shift=False, ctrl=False, alt=False, meta=False
                )
            )
            self.assertEqual(
                editor.documents[editor.current].messages[editor.message_index].name,
                "c2s_create_build",
            )
            self.assertEqual(editor.file_search.hint_text, "搜索文件，回车打开")
            self.assertTrue(editor.file_search.ignore_up_down_keys)
            self.assertEqual(editor.file_search.on_submit, editor._open_search_target)

    def test_type_matches_ranks_prefix_then_substring_then_letters(self):
        options = ["int32", "string", "Common.p_item", "p_build_info", "bytes"]
        self.assertEqual(type_matches(options, "p_"), ["Common.p_item", "p_build_info"])
        self.assertEqual(type_matches(options, "item"), ["Common.p_item"])
        self.assertEqual(type_matches(options, "pbi"), ["p_build_info"])
        self.assertEqual(type_matches(options, "string")[0], "string")
        self.assertEqual(len(type_matches(options, "string")), len(options))
        self.assertEqual(type_matches(options, "zzz"), [])

    def test_field_row_toggles_kind_and_completes_types(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            source = root / "proto"
            source.mkdir()
            (source / "build.proto").write_text(
                'syntax = "proto3";\n\npackage Build;\n\n'
                "message p_build_info {\n\tint32 id = 1;\n}\n"
                "message c2s_create_build {\n\tint32 bid = 1;\n}\n",
                encoding="utf-8",
            )

            class FakeContext:
                def dialog_width(self, preferred):
                    return preferred

                def dialog_height(self, preferred, margin=80):
                    return preferred

                def update(self):
                    pass

            editor = ProtocolEditor(FakeContext(), tools, source)
            editor.rebuild()
            document = editor._document()
            message = document.messages[1]
            item = message.fields[0]
            row = editor._field_row(document, message, item)
            kind_box = row.controls[0].content
            type_box = row.controls[1].content
            self.assertIsInstance(kind_box, ft.TextField)
            self.assertEqual(kind_box.value, "单个")
            self.assertEqual(kind_box.width, 72)

            def choose(control, value):
                control.on_click(None)
                chips = {
                    chip.content.value: chip for chip in editor.suggestions.controls
                }
                self.assertEqual(list(chips), ["单个", "数组", "字典"])
                chips[value].on_click(None)

            type_box.on_focus(SimpleNamespace(control=type_box))
            type_box.value = "pbi"
            type_box.on_change(SimpleNamespace(control=type_box))
            chips = [chip.content.value for chip in editor.suggestions.controls]
            self.assertEqual(chips, ["p_build_info"])
            type_box.on_submit(SimpleNamespace(control=type_box))
            self.assertEqual(item.type_name, "p_build_info")
            self.assertEqual(type_box.value, "p_build_info")

            type_box.value = "Other.p_custom"
            type_box.on_change(SimpleNamespace(control=type_box))
            type_box.on_submit(SimpleNamespace(control=type_box))
            self.assertEqual(item.type_name, "Other.p_custom")

            choose(kind_box, "数组")
            self.assertTrue(item.repeated)
            row = editor._field_row(document, message, item)
            choose(row.controls[0].content, "字典")
            self.assertEqual(item.map_key, "int32")
            row = editor._field_row(document, message, item)
            key_box, value_box, value_kind = row.controls[1].controls
            self.assertEqual(key_box.hint_text, "键")
            self.assertEqual(value_box.hint_text, "值")
            value_box.on_focus(SimpleNamespace(control=value_box))
            value_box.value = "pbi"
            value_box.on_change(SimpleNamespace(control=value_box))
            chips = [chip.content.value for chip in editor.suggestions.controls]
            self.assertEqual(chips, ["p_build_info"])
            value_box.on_submit(SimpleNamespace(control=value_box))
            self.assertEqual(item.map_value, "p_build_info")
            key_box.on_focus(SimpleNamespace(control=key_box))
            key_box.value = "str"
            key_box.on_change(SimpleNamespace(control=key_box))
            chips = [chip.content.value for chip in editor.suggestions.controls]
            self.assertEqual(chips, ["string"])
            self.assertEqual(value_kind.value, "单个")
            value_kind.on_click(None)
            self.assertEqual(value_kind.value, "数组")
            self.assertTrue(item.map_value_repeated)
            self.assertTrue(document.dirty)

    def test_ctrl_s_saves_and_source_mode_round_trips(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            source = root / "proto"
            source.mkdir()
            path = source / "build.proto"
            path.write_text(
                'syntax = "proto3";\n\npackage Build;\n\n'
                "message c2s_create_build {\n\tint32 bid = 1;\n}\n",
                encoding="utf-8",
            )

            class FakeContext:
                def dialog_width(self, preferred):
                    return preferred

                def dialog_height(self, preferred, margin=80):
                    return preferred

                def update(self):
                    pass

                def notify(self, message, error=False):
                    pass

            editor = ProtocolEditor(FakeContext(), tools, source)
            editor.rebuild()
            editor.documents[path].messages[0].fields[0].name = "build_id"
            editor.documents[path].dirty = True
            handled = editor._on_key(
                SimpleNamespace(key="S", shift=False, ctrl=True, alt=False, meta=False)
            )
            self.assertTrue(handled)
            self.assertIn("int32 build_id = 1;", path.read_text(encoding="utf-8"))
            self.assertFalse(editor._is_dirty(path))

            editor.toggle_source()
            self.assertTrue(editor.source_mode)
            editor.source_text[path] = path.read_text(encoding="utf-8").replace(
                "build_id = 1;", "build_id = 1;\n\tstring name = 2;"
            )
            self.assertTrue(editor._is_dirty(path))
            editor._on_key(
                SimpleNamespace(key="s", shift=False, ctrl=True, alt=False, meta=False)
            )
            self.assertIn("string name = 2;", path.read_text(encoding="utf-8"))
            self.assertEqual(len(editor.documents[path].messages[0].fields), 2)
            self.assertFalse(editor._is_dirty(path))

            editor.source_text[path] = "message broken {"
            editor.toggle_source()
            self.assertTrue(editor.source_mode)
            self.assertIn("源码还不能用表格编辑", editor.status.value)
            editor.source_text[path] = path.read_text(encoding="utf-8")
            editor.toggle_source()
            self.assertFalse(editor.source_mode)

    def test_enter_opens_matching_protocol_and_arrows_move_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            source = root / "proto"
            source.mkdir()
            (source / "build.proto").write_text(
                'syntax = "proto3";\n\npackage Build;\n\n'
                "message s2c_req_all_build_end {\n}\n",
                encoding="utf-8",
            )
            (source / "login.proto").write_text(
                'syntax = "proto3";\n\npackage Login;\n\n'
                "message c2s_user_login {\n\tstring account = 1;\n}\n",
                encoding="utf-8",
            )

            class FakeContext:
                def dialog_width(self, preferred):
                    return preferred

                def dialog_height(self, preferred, margin=80):
                    return preferred

                def update(self):
                    pass

                def show_dialog(self, dialog, on_close=None):
                    pass

                def notify(self, message, error=False):
                    pass

                def focus(self, control):
                    pass

            editor = ProtocolEditor(FakeContext(), tools, source)
            editor.rebuild()
            editor.search_focused = True
            editor.file_query = "c2s_user"
            editor.file_search.value = "c2s_user"
            editor._open_search_target()
            self.assertEqual(editor.current.name, "login.proto")
            self.assertEqual(
                editor.documents[editor.current].messages[editor.message_index].name,
                "c2s_user_login",
            )

            editor.file_query = ""
            editor._fill_file_list()
            editor.search_focused = True
            editor._on_key(
                SimpleNamespace(key="Arrow Up", shift=False, ctrl=False, alt=False, meta=False)
            )
            self.assertEqual(editor.current.name, "build.proto")
            editor._on_key(
                SimpleNamespace(
                    key="Arrow Down", shift=False, ctrl=False, alt=False, meta=False
                )
            )
            self.assertEqual(editor.current.name, "login.proto")
            editor.search_focused = False
            editor._on_key(
                SimpleNamespace(key="Arrow Up", shift=False, ctrl=False, alt=False, meta=False)
            )
            self.assertEqual(editor.current.name, "login.proto")

    def test_page_keyboard_reaches_the_protocol_editor(self):
        page = FakePage()
        with (
            patch("app_settings._load_app_settings", return_value=({}, None)),
            patch("plugin_host.user_plugin_directory", return_value=Path(".")),
        ):
            main(page)
        self.assertEqual(page.window.min_width, 960)
        self.assertEqual(page.window.min_height, 680)
        self.assertIsNone(getattr(page.window, "alignment", None))
        seen = []
        page.on_keyboard_event.__self__.plugin_keyboard_handler = (
            lambda event: seen.append(event.key) or True
        )
        page.on_keyboard_event(
            ft.KeyboardEvent(
                name="keyboard",
                control=page,
                key="Arrow Down",
                shift=False,
                ctrl=False,
                alt=False,
                meta=False,
            )
        )
        self.assertEqual(seen, ["Arrow Down"])

    def test_delete_proto_file_removes_it_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tools = _tools_tree(root)
            source = root / "proto"
            source.mkdir()
            (source / "build.proto").write_text('syntax = "proto3";\n', encoding="utf-8")
            (source / "login.proto").write_text('syntax = "proto3";\n', encoding="utf-8")
            dialogs = []

            class FakeContext:
                def dialog_width(self, preferred):
                    return preferred

                def dialog_height(self, preferred, margin=80):
                    return preferred

                def update(self):
                    pass

                def show_dialog(self, dialog, on_close=None):
                    dialogs.append(dialog)

                def pop_dialog(self):
                    if dialogs:
                        dialogs.pop()

                def notify(self, message, error=False):
                    pass

                def focus(self, control):
                    pass

            editor = ProtocolEditor(FakeContext(), tools, source)
            editor.rebuild()
            self.assertEqual(editor.current.name, "build.proto")
            editor.delete_current_file()
            confirm = _button_by_content(dialogs[-1], "删除")
            confirm.on_click(None)

            self.assertFalse((source / "build.proto").exists())
            self.assertTrue((source / "login.proto").exists())
            self.assertEqual(editor.current.name, "login.proto")

    def test_new_proto_file_uses_proto3_and_a_package_name(self):
        self.assertEqual(normalize_proto_filename("login"), "login.proto")
        self.assertEqual(normalize_proto_filename("login.proto"), "login.proto")
        self.assertIsNone(normalize_proto_filename("login file"))
        text = new_proto_text("login.proto")
        self.assertIn('syntax = "proto3";', text)
        self.assertIn("package Login;", text)


class ProtoDocumentTests(unittest.TestCase):
    def test_repository_proto_files_keep_messages_and_fields(self):
        proto_dir = Path(__file__).resolve().parents[2] / "proto"
        files = list(proto_dir.glob("*.proto"))
        self.assertGreaterEqual(len(files), 1)
        for path in files:
            document = parse_proto(path.read_text(encoding="utf-8-sig"))
            again = parse_proto(render_proto(document))
            self.assertEqual(
                [(item.name, item.comment, [(field.name, field.number, field.comment, field.repeated, field.type_name, field.map_key, field.map_value) for field in item.fields]) for item in document.messages],
                [(item.name, item.comment, [(field.name, field.number, field.comment, field.repeated, field.type_name, field.map_key, field.map_value) for field in item.fields]) for item in again.messages],
            )
            self.assertEqual(validate_document(path.name, document, proto_dir), [])

    def test_common_types_cannot_use_protocol_prefix(self):
        self.assertIsNotNone(message_name_error("common.proto", "c2s_reward"))
        self.assertIsNone(message_name_error("common.proto", "p_reward_info"))
        self.assertIsNone(message_name_error("login.proto", "p_reward_info"))
        self.assertIsNone(message_name_error("caravan.proto", "notify_caravan_play"))
        self.assertIsNone(message_name_error("chat.proto", "c2sChat"))
        self.assertIsNotNone(message_name_error("chat.proto", "1bad"))

    def test_mixed_protocol_file_saves_with_aligned_comments(self):
        document = parse_proto(
            'syntax = "proto3";\n\npackage caravan;\n\n'
            "message CaravanSimpleRecordItem {\n    uint64 damage = 1;\n}\n\n"
            "message notify_caravan_state{\n"
            "\tmap<uint64, uint32> caravan_state_map = 1; // 商队状态\n"
            "\tuint32 n = 2;\t//数量\n}\n\n"
            "//请求必争之城数量\nmessage c2s_get_caravan_keycity{\n}\n"
        )
        self.assertEqual(validate_document("caravan.proto", document), [])
        self.assertEqual(
            [message_kind(item.name) for item in document.messages],
            ["type", "notify", "c2s"],
        )
        rendered = render_proto(document)
        self.assertIn(
            "\tmap<uint64, uint32> caravan_state_map = 1;  // 商队状态\n"
            f"\t{'uint32 n = 2;'.ljust(len('map<uint64, uint32> caravan_state_map = 1;'))}  // 数量\n",
            rendered,
        )
        self.assertIn("// 请求必争之城数量\nmessage c2s_get_caravan_keycity {\n}", rendered)
        self.assertEqual(render_proto(parse_proto(rendered)), rendered)

    def test_unknown_field_type_is_rejected(self):
        missing = parse_proto(
            'syntax = "proto3";\n\npackage caravan;\n\n'
            "message c2s_load {\n\tNoSuch info = 1;\n"
            "\tmap<uint32, AlsoMissing> gifts = 2;\n}\n"
        )
        errors = validate_document("caravan.proto", missing)
        self.assertIn("c2s_load.info：不支持的类型 NoSuch", errors)
        self.assertIn("c2s_load.gifts：不支持的类型 AlsoMissing", errors)
        present = parse_proto(
            'syntax = "proto3";\n\npackage caravan;\n\n'
            "message CaravanPlayInfo {\n\tuint32 id = 1;\n}\n"
            "message c2s_load {\n\tCaravanPlayInfo info = 1;\n}\n"
        )
        self.assertEqual(validate_document("caravan.proto", present), [])

    def test_map_and_repeated_fields_round_trip(self):
        document = parse_proto(
            "\n".join(
                [
                    'syntax = "proto3";',
                    "package User;",
                    "message c2s_user_res {",
                    "    map<int32, string> res = 1; // 资源",
                    "    repeated int32 ids = 2;",
                    "}",
                    "",
                ]
            )
        )
        rendered = render_proto(document)
        again = parse_proto(rendered)
        original = document.messages[0].fields
        copied = again.messages[0].fields
        self.assertEqual(
            [(item.map_key, item.map_value, item.repeated, item.type_name, item.name, item.number, item.comment) for item in original],
            [("int32", "string", False, "", "res", 1, "资源"), ("", "", True, "int32", "ids", 2, "")],
        )
        self.assertEqual(
            [(item.map_key, item.map_value, item.repeated, item.type_name, item.name) for item in copied],
            [(item.map_key, item.map_value, item.repeated, item.type_name, item.name) for item in original],
        )
        self.assertEqual(validate_document("user.proto", document), [])
        self.assertIn("map<int32, string> res = 1;  // 资源", rendered)
        self.assertIn("repeated int32 ids = 2;", rendered)

        document.messages[0].fields[0].map_value_repeated = True
        rendered = render_proto(document)
        again = parse_proto(rendered)
        mapped = again.messages[0].fields[0]
        self.assertEqual(mapped.map_key, "int32")
        self.assertEqual(mapped.map_value, "string")
        self.assertTrue(mapped.map_value_repeated)
        self.assertEqual([item.name for item in again.messages], ["c2s_user_res"])
        self.assertIn("map<int32, p_map_c2s_user_res_res_list> res = 1;  // 资源", rendered)
        self.assertIn("message p_map_c2s_user_res_res_list {", rendered)
        self.assertIn("repeated string value = 1;", rendered)
        self.assertEqual(validate_document("user.proto", again), [])

        document.messages[0].fields[0].map_key = "float"
        errors = validate_document("user.proto", document)
        self.assertTrue(any("字典的键" in error for error in errors))

    def test_field_type_options_include_scalars_and_imported_messages(self):
        proto_dir = Path(__file__).resolve().parents[2] / "proto"
        document = parse_proto((proto_dir / "mail.proto").read_text(encoding="utf-8-sig"))
        options = field_type_options(proto_dir, document, "int32")
        self.assertIn("int32", options)
        self.assertIn("string", options)
        self.assertIn("Common.p_mail_info", options)
        self.assertIn("Common.p_reward_info", options)


class PluginInstallTests(unittest.TestCase):
    def test_catalog_stays_inactive_until_installed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            installed = Path(temporary_directory)
            packages = list_plugin_packages(installed=installed)
            protocol = next(package for package in packages if package.plugin_id == "protocol_export")
            self.assertEqual(protocol.title, "协议")
            self.assertFalse(protocol.installed)
            actions, errors = load_plugins(object(), [installed])
            self.assertEqual(errors, [])
            self.assertEqual(actions, [])

            install_plugin("protocol_export", destination=installed)
            actions, errors = load_plugins(object(), [installed])
            self.assertEqual([action.label for action in actions], ["协议"])

            uninstall_plugin("protocol_export", destination=installed)
            actions, errors = load_plugins(object(), [installed])
            self.assertEqual(actions, [])


class ProtocolButtonTests(unittest.TestCase):
    @staticmethod
    def _header_actions(page):
        header = page.controls[0].controls[1].content.controls[0]
        return header.content.controls[2]

    def test_protocol_export_appears_only_after_install(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            installed = Path(temporary_directory)
            page = FakePage()
            with (
                patch("app_settings._load_app_settings", return_value=({}, None)),
                patch("plugin_host.user_plugin_directory", return_value=installed),
            ):
                main(page)
            labels = [control.content for control in self._header_actions(page).controls]
            self.assertIn("插件", labels)
            self.assertNotIn("协议", labels)

            install_plugin("protocol_export", destination=installed)
            installed_page = FakePage()
            with (
                patch("app_settings._load_app_settings", return_value=({}, None)),
                patch("plugin_host.user_plugin_directory", return_value=installed),
            ):
                main(installed_page)
                labels = [
                    control.content
                    for control in self._header_actions(installed_page).controls
                ]
                self.assertNotIn("协议", labels)
                plugin_button = next(
                    control
                    for control in self._header_actions(installed_page).controls
                    if control.content == "插件"
                )
                plugin_button.on_click(None)
                self.assertIn("打开", self._button_labels(installed_page.dialogs[-1]))

    @staticmethod
    def _button_labels(control, seen=None):
        if seen is None:
            seen = set()
        if control is None or id(control) in seen:
            return []
        seen.add(id(control))
        labels = []
        content = getattr(control, "content", None)
        if isinstance(content, str):
            labels.append(content)
        for child in getattr(control, "controls", None) or []:
            labels.extend(ProtocolButtonTests._button_labels(child, seen))
        if not isinstance(content, str):
            labels.extend(ProtocolButtonTests._button_labels(content, seen))
        return labels
