import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_extractlua():
    path = Path(__file__).resolve().parents[2] / "ptotools" / "script" / "extractlua.py"
    spec = importlib.util.spec_from_file_location("extractlua", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extractlua = _load_extractlua()


class NetPbTests(unittest.TestCase):
    def test_assigns_ids_by_filename_then_source_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "common.proto").write_text(
                "syntax = \"proto3\";\nmessage c2s_ignored {}\nmessage p_info {}\n",
                encoding="utf-8",
            )
            (root / "zeta.proto").write_text(
                "\n".join(
                    [
                        "syntax = \"proto3\";",
                        "// message c2s_commented {}",
                        "message p_detail {}",
                        "message s2cChat {}",
                        "message notify_kick {}",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "alpha.proto").write_text(
                "syntax = \"proto3\";\nmessage c2s_login {}\nmessage s2c_login {}\n",
                encoding="utf-8",
            )

            entries = extractlua.collect_protocol_ids(str(root))

        self.assertEqual(
            entries,
            [
                ("c2s_login", 1),
                ("s2c_login", 2),
                ("s2cChat", 3),
                ("notify_kick", 4),
            ],
        )

    def test_same_name_in_different_packages_is_qualified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "login.proto").write_text(
                "package Login;\nmessage s2c_user_create {}\n",
                encoding="utf-8",
            )
            (root / "user.proto").write_text(
                "package User;\nmessage c2s_user_base_info {}\nmessage s2c_user_create {}\n",
                encoding="utf-8",
            )

            protocols = extractlua.collect_protocols(str(root))

        self.assertEqual(
            [(entry.key, entry.proto_id) for entry in protocols],
            [
                ("Login.s2c_user_create", 1),
                ("c2s_user_base_info", 2),
                ("User.s2c_user_create", 3),
            ],
        )
        lua = extractlua.render_net_pb_lua(protocols)
        self.assertIn("['Login'] = {\n\t\t['s2c_user_create'] = 1,", lua)
        self.assertIn("['User'] = {\n\t\t['c2s_user_base_info'] = 2,\n\t\t['s2c_user_create'] = 3,", lua)
        self.assertEqual(
            json.loads(extractlua.render_net_pb_json(protocols)),
            {
                "define": {
                    "Login": {"s2c_user_create": 1},
                    "User": {"c2s_user_base_info": 2, "s2c_user_create": 3},
                }
            },
        )

    def test_same_package_and_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.proto").write_text(
                "package Login;\nmessage c2s_login {}\n",
                encoding="utf-8",
            )
            (root / "b.proto").write_text(
                "package Login;\nmessage c2s_login {}\n",
                encoding="utf-8",
            )
            with self.assertRaises(extractlua.ProtocolIdError):
                extractlua.collect_protocol_ids(str(root))

    def test_writes_client_json_and_server_lua(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proto_dir = root / "proto"
            proto_dir.mkdir()
            (proto_dir / "login.proto").write_text(
                "message c2s_login {}\nmessage s2c_login {}\n",
                encoding="utf-8",
            )
            json_path = root / "client" / "proto" / "net_pb.json"
            lua_path = root / "server" / "proto" / "net_pb.lua"

            extractlua.write_net_pb(str(proto_dir), str(json_path), str(lua_path))

            self.assertEqual(
                json.loads(json_path.read_text(encoding="utf-8")),
                {"define": {"login": {"c2s_login": 1, "s2c_login": 2}}},
            )
            lua = lua_path.read_text(encoding="utf-8")
            self.assertIn("['login'] = {", lua)
            self.assertIn("['c2s_login'] = 1,", lua)
            self.assertIn("['s2c_login'] = 2,", lua)
            self.assertNotIn("return {", lua)
            self.assertIn("ID_TO_PACK_NAME[id] = packName", lua)
            self.assertIn("PTONAME_TO_ID[ptoName] = id", lua)
            self.assertIn("PACK_NAME_TO_ID[packName] = id", lua)
            self.assertIn("ID_TO_PTONAME[id] = ptoName", lua)
            self.assertIn("for_maker = {}", lua)
            self.assertIn("for_caller = {}", lua)
            self.assertLess(lua.index("local define"), lua.index("local function initPto()"))
            self.assertTrue(lua.rstrip().endswith("initPto()"))
            self.assertTrue(lua.startswith("-- author: liter_wave\n"))


if __name__ == "__main__":
    unittest.main()
