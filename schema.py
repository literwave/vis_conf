PAGE_SIZES = (10, 20, 50, 100)

MAX_ROW_UNDO = 50

SAMPLE_COLUMNS = ["id", "name", "type", "rarity", "price"]

DATA_TYPES = {
    "string": "字符串",
    "integer": "整数",
    "number": "小数",
    "boolean": "布尔值",
    "json": "JSON（对象/数组）",
    "lua_array": "Lua 表（数组）",
    "lua_object": "Lua 表（字典）",
}

EXPORT_TARGETS = {"both": "前后端", "backend": "仅后端", "frontend": "仅前端"}

SAMPLE_TYPES = ["integer", "string", "string", "string", "integer"]

SAMPLE_TARGETS = ["both", "both", "both", "both", "both"]

SAMPLE_ANNOTATIONS = ["唯一标识", "道具名称", "道具分类", "品质等级", "商店价格"]

SAMPLE_ROWS = [
    {"id": 1001, "name": "新手长剑", "type": "武器", "rarity": "普通", "price": 100},
    {"id": 1002, "name": "旅人法杖", "type": "武器", "rarity": "精良", "price": 420},
    {"id": 1003, "name": "生命药水", "type": "消耗品", "rarity": "普通", "price": 35},
    {"id": 1004, "name": "秘银护甲", "type": "防具", "rarity": "稀有", "price": 1250},
    {"id": 1005, "name": "疾风靴", "type": "防具", "rarity": "精良", "price": 680},
    {"id": 1006, "name": "火焰卷轴", "type": "消耗品", "rarity": "稀有", "price": 900},
    {"id": 1007, "name": "守护指环", "type": "饰品", "rarity": "精良", "price": 760},
    {"id": 1008, "name": "星辰碎片", "type": "材料", "rarity": "史诗", "price": 3200},
    {"id": 1009, "name": "铁矿石", "type": "材料", "rarity": "普通", "price": 12},
    {"id": 1010, "name": "远古护符", "type": "饰品", "rarity": "传说", "price": 8600},
    {"id": 1011, "name": "冰霜短刃", "type": "武器", "rarity": "稀有", "price": 1750},
    {
        "id": 1012,
        "name": "强效回复药",
        "type": "消耗品",
        "rarity": "精良",
        "price": 160,
    },
    {"id": 1013, "name": "秘银矿石", "type": "材料", "rarity": "稀有", "price": 340},
    {"id": 1014, "name": "游侠斗篷", "type": "防具", "rarity": "史诗", "price": 4100},
    {"id": 1015, "name": "月光宝石", "type": "材料", "rarity": "史诗", "price": 5200},
    {"id": 1016, "name": "勇者徽章", "type": "饰品", "rarity": "传说", "price": 9800},
    {"id": 1017, "name": "橡木弓", "type": "武器", "rarity": "普通", "price": 150},
    {"id": 1018, "name": "净化药剂", "type": "消耗品", "rarity": "精良", "price": 230},
]
