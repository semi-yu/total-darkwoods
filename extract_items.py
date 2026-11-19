#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DarkWood2 (ForestOfSteel) Dynamic Unity Item Data Extractor CLI
Milestone 1: Unity 에디터 실행 없이 C# 스크립트(.cs/.cs.meta)와 YAML 에셋(.asset/.meta)을
동적으로 분석하여 확장 가능한 items.json을 생성합니다.

핵심 설계:
- 아이템 대분류(itemType), ScriptableObject 파생 클래스, Enum 정의, 직렬화 필드를
  하드코딩하지 않고 Unity 프로젝트의 C# 소스 코드 및 .meta 파일에서 자동 탐색(Auto-Discovery)합니다.
- 새로운 ItemData 파생 클래스나 새로운 대분류/필드가 추가되어도 스크립트나 스키마 수정 없이
  자동으로 `categories`, `classSchemas`, `enumSchemas` 및 각 아이템의 `attributes`에 반영됩니다.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Set, Tuple


BASE_ITEM_FIELDS: Set[str] = {
    "_itemId",
    "_displayName",
    "_description",
    "_icon",
    "_worldSprite",
    "_maxStack",
}

UNITY_BUILTIN_ENUMS: Dict[str, Dict[int, str]] = {
    "SpriteSortPoint": {0: "Center", 1: "Pivot"},
}


# ============================================================================
# 1. 공통 포맷팅 및 Unity YAML 파서 유틸리티
# ============================================================================

def round_to_int(val: float) -> int:
    return int(round(val))


def fmt_fixed(val: float, decimals: int) -> str:
    q = Decimal("1") if decimals == 0 else Decimal("0." + "0" * decimals)
    d = Decimal(str(val)).quantize(q, rounding=ROUND_HALF_UP)
    return f"{d:.{decimals}f}"


def format_duration_ko(seconds: float) -> str:
    total = max(0, int(math.ceil(seconds)))
    if total < 60:
        return f"{total}초"
    minutes = total // 60
    rest = total % 60
    return f"{minutes}분" if rest == 0 else f"{minutes}분 {rest}초"


def field_to_camel(field_name: str) -> str:
    """`_harvestToolType` -> `harvestToolType`"""
    clean = field_name.lstrip("_")
    if not clean:
        return field_name
    return clean[0].lower() + clean[1:]


def decode_unity_quoted_string(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        inner = raw[1:-1]
        inner = re.sub(r"\r?\n\s*", " ", inner)

        def replace_escape(match: re.Match) -> str:
            seq = match.group(0)
            if seq.startswith("\\u") and len(seq) == 6:
                return chr(int(seq[2:], 16))
            if seq.startswith("\\U") and len(seq) == 10:
                return chr(int(seq[2:], 16))
            if seq.startswith("\\x") and len(seq) == 4:
                return chr(int(seq[2:], 16))
            escapes = {
                '\\"': '"',
                "\\\\": "\\",
                "\\/": "/",
                "\\b": "\b",
                "\\f": "\f",
                "\\n": "\n",
                "\\r": "\r",
                "\\t": "\t",
            }
            return escapes.get(seq, seq[1:])

        return re.sub(r'\\(?:u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|x[0-9a-fA-F]{2}|.)', replace_escape, inner)
    elif len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        inner = raw[1:-1]
        inner = re.sub(r"\r?\n\s*", " ", inner)
        return inner.replace("''", "'")
    return raw


def parse_inline_dict(raw: str) -> Dict[str, Any]:
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return {}
    result: Dict[str, Any] = {}
    for part in inner.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        result[k.strip()] = parse_scalar(v.strip())
    return result


def parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw == "" or raw == "~" or raw == "null":
        return None
    if raw == "[]":
        return []
    if raw.startswith("{") and raw.endswith("}"):
        return parse_inline_dict(raw)
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return decode_unity_quoted_string(raw)
    if re.fullmatch(r"-?\d+", raw):
        try:
            return int(raw)
        except ValueError:
            pass
    if re.fullmatch(r"-?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?", raw):
        try:
            return float(raw)
        except ValueError:
            pass
    return raw


def parse_unity_monobehaviour_yaml(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8", errors="replace") as fp:
        lines = fp.readlines()

    data: Dict[str, Any] = {}
    in_mono = False
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("MonoBehaviour:"):
            in_mono = True
            i += 1
            continue
        if not in_mono:
            i += 1
            continue
        if stripped.startswith("--- "):
            break

        m = re.match(r"^  ([A-Za-z0-9_]+):(.*)$", line.rstrip("\r\n"))
        if not m:
            i += 1
            continue

        key = m.group(1)
        val_str = m.group(2).strip()

        if (val_str.startswith('"') and not (len(val_str) > 1 and val_str.endswith('"') and not val_str.endswith('\\"'))) or (
            val_str.startswith("'") and not (len(val_str) > 1 and val_str.endswith("'"))
        ):
            quote_char = val_str[0]
            acc = [val_str]
            i += 1
            while i < n:
                next_line = lines[i].rstrip("\r\n")
                acc.append(next_line)
                s = next_line.strip()
                if s.endswith(quote_char) and not s.endswith("\\" + quote_char):
                    break
                i += 1
            data[key] = decode_unity_quoted_string("\n".join(acc))
            i += 1
            continue

        if val_str == "":
            if i + 1 < n and re.match(r"^  -\s+", lines[i + 1]):
                items_list: List[Dict[str, Any]] = []
                i += 1
                curr_item: Optional[Dict[str, Any]] = None
                while i < n:
                    l_raw = lines[i].rstrip("\r\n")
                    m_item_start = re.match(r"^  -\s+([A-Za-z0-9_]+):\s*(.*)$", l_raw)
                    m_item_prop = re.match(r"^    ([A-Za-z0-9_]+):\s*(.*)$", l_raw)
                    if m_item_start:
                        if curr_item is not None:
                            items_list.append(curr_item)
                        curr_item = {m_item_start.group(1): parse_scalar(m_item_start.group(2))}
                        i += 1
                    elif m_item_prop and curr_item is not None:
                        curr_item[m_item_prop.group(1)] = parse_scalar(m_item_prop.group(2))
                        i += 1
                    else:
                        break
                if curr_item is not None:
                    items_list.append(curr_item)
                data[key] = items_list
                continue
            else:
                data[key] = ""
                i += 1
                continue

        acc_unquoted = [val_str]
        while i + 1 < n:
            peek = lines[i + 1].rstrip("\r\n")
            if peek.startswith("    ") and not re.match(r"^\s*-\s+", peek) and ":" not in peek:
                acc_unquoted.append(peek.strip())
                i += 1
            else:
                break
        if len(acc_unquoted) > 1:
            data[key] = parse_scalar(" ".join(acc_unquoted))
        else:
            data[key] = parse_scalar(val_str)
        i += 1

    return data


# ============================================================================
# 2. 동적 C# 스크립트 분석기 (클래스, 상속, 필드, Enum, UI 포맷터 자동 탐색)
# ============================================================================

class CSharpSchemaDiscoverer:
    """
    Unity 프로젝트의 C# 스크립트(.cs 및 .cs.meta)를 정적 분석하여
    ItemData 상속 계층, 직렬화 필드, Enum 정의, 한글 표시명 규칙을 동적으로 추출합니다.
    """

    def __init__(self, scripts_root: str, base_class: str = "ItemData") -> None:
        self.scripts_root = os.path.abspath(scripts_root)
        self.base_class = base_class
        self.enums: Dict[str, Dict[int, str]] = dict(UNITY_BUILTIN_ENUMS)
        self.enum_member_comments: Dict[str, Dict[str, str]] = {}
        self.enum_switch_labels: Dict[str, Dict[str, str]] = {}
        self.raw_classes: Dict[str, Dict[str, Any]] = {}
        self.item_classes: Dict[str, Dict[str, Any]] = {}
        self.guid_to_class: Dict[str, str] = {}
        self.type_name_rules: List[Dict[str, Any]] = []
        self.default_type_name_ko: str = "재료"

    def discover(self) -> None:
        if not os.path.isdir(self.scripts_root):
            return

        cs_files = sorted(glob.glob(os.path.join(self.scripts_root, "**", "*.cs"), recursive=True))
        for cs_path in cs_files:
            with open(cs_path, "r", encoding="utf-8", errors="ignore") as fp:
                text = fp.read()
            guid = self._read_meta_guid(cs_path + ".meta")
            self._parse_enums_from_text(text)
            self._parse_switch_labels_from_text(text)
            self._parse_classes_from_text(text, cs_path, guid)
            if os.path.basename(cs_path) == "ItemUIFormatter.cs":
                self._parse_type_name_rules(text)

        # ItemData 및 모든 파생 클래스(다단계 상속 포함) 탐색
        discovered: Set[str] = {self.base_class} if self.base_class in self.raw_classes else set()
        changed = True
        while changed:
            changed = False
            for cname, cinfo in self.raw_classes.items():
                if cname not in discovered and any(b in discovered for b in cinfo["bases"]):
                    discovered.add(cname)
                    changed = True

        for cname in sorted(discovered):
            cinfo = self.raw_classes[cname]
            if cinfo["guid"]:
                self.guid_to_class[cinfo["guid"]] = cname
            cinfo["fields"] = self._parse_serialized_fields(cinfo["body"])
            cinfo["equipmentCategoryRule"] = self._parse_equipment_category_rule(cinfo["body"])
            self.item_classes[cname] = cinfo

    @staticmethod
    def _read_meta_guid(meta_path: str) -> Optional[str]:
        if not os.path.isfile(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8", errors="ignore") as fp:
                head = fp.read(256)
            m = re.search(r"^guid:\s*([0-9a-fA-F]+)", head, re.MULTILINE)
            return m.group(1) if m else None
        except OSError:
            return None

    def _parse_enums_from_text(self, text: str) -> None:
        for m in re.finditer(r"public\s+enum\s+(\w+)\s*(?::\s*\w+)?\s*\{([^}]+)\}", text):
            ename = m.group(1)
            ebody = m.group(2)
            members: Dict[int, str] = {}
            comments: Dict[str, str] = {}
            curr_val = 0
            for line in ebody.splitlines():
                comment_match = re.search(r"//\s*(.+)$", line)
                comment_text = comment_match.group(1).strip() if comment_match else ""
                clean = re.sub(r"//.*", "", line).strip().rstrip(",")
                if not clean:
                    continue
                if "=" in clean:
                    k, v = clean.split("=", 1)
                    member_name = k.strip()
                    try:
                        curr_val = int(v.strip())
                    except ValueError:
                        pass
                else:
                    member_name = clean
                members[curr_val] = member_name
                if comment_text:
                    # 괄호 부연설명 제거 후 간결한 한글 라벨 추출
                    short_comment = re.sub(r"\s*\([^)]*\)", "", comment_text).strip()
                    comments[member_name] = short_comment
                curr_val += 1
            self.enums[ename] = members
            if comments:
                self.enum_member_comments[ename] = comments

    def _parse_switch_labels_from_text(self, text: str) -> None:
        for m in re.finditer(r'case\s+(\w+)\.(\w+):\s*(?:\r?\n\s*)?return\s*"([^"]*)";', text):
            ename, emember, label = m.groups()
            self.enum_switch_labels.setdefault(ename, {})[emember] = label

    def _parse_classes_from_text(self, text: str, cs_path: str, guid: Optional[str]) -> None:
        pattern = re.compile(
            r'(?:\[CreateAssetMenu\((?P<menu>[^\]]+)\)\]\s*)?'
            r'public\s+(?:sealed\s+|abstract\s+)?class\s+(?P<name>\w+)\s*:\s*(?P<bases>[^{\r\n]+)\s*\{',
            re.MULTILINE,
        )
        for m in pattern.finditer(text):
            cname = m.group("name")
            bases = [b.strip() for b in m.group("bases").split(",")]
            menu_raw = m.group("menu") or ""
            menu_name_m = re.search(r'menuName\s*=\s*"([^"]+)"', menu_raw)
            file_name_m = re.search(r'fileName\s*=\s*"([^"]+)"', menu_raw)

            # 중괄호 매칭으로 클래스 본문 추출
            start_idx = m.end()
            depth = 1
            idx = start_idx
            while idx < len(text) and depth > 0:
                if text[idx] == "{":
                    depth += 1
                elif text[idx] == "}":
                    depth -= 1
                idx += 1
            body = text[start_idx : idx - 1]

            self.raw_classes[cname] = {
                "name": cname,
                "bases": bases,
                "guid": guid,
                "path": cs_path,
                "menuName": menu_name_m.group(1) if menu_name_m else None,
                "fileNamePrefix": file_name_m.group(1) if file_name_m else None,
                "body": body,
            }

    def _parse_serialized_fields(self, class_body: str) -> List[Dict[str, Any]]:
        fields: List[Dict[str, Any]] = []
        curr_header: Optional[str] = None
        curr_tooltip: Optional[str] = None
        pending_serialize = False

        for line in class_body.splitlines():
            s = line.strip()
            if not s or s.startswith("//"):
                continue

            hm = re.search(r'\[Header\("([^"]+)"\)\]', s)
            if hm:
                curr_header = hm.group(1)

            tm = re.search(r'\[Tooltip\("([^"]+)"\)\]', s)
            if tm:
                curr_tooltip = tm.group(1)

            if "[SerializeField]" in s:
                pending_serialize = True

            if pending_serialize and ";" in s:
                # 어트리뷰트 대괄호들을 제거한 뒤 필드 선언부 추출
                decl = re.sub(r"\[[^\]]*\]", "", s).strip()
                fm = re.match(
                    r"(?:private|protected|public)\s+([\w<>\[\]]+)\s+(_\w+)(?:\s*=\s*([^;]+))?;",
                    decl,
                )
                if fm:
                    cs_type = fm.group(1).strip()
                    raw_name = fm.group(2).strip()
                    default_expr = (fm.group(3) or "").strip()
                    fields.append({
                        "rawName": raw_name,
                        "name": field_to_camel(raw_name),
                        "csharpType": cs_type,
                        "defaultExpr": default_expr,
                        "defaultValue": self.eval_csharp_default(cs_type, default_expr),
                        "header": curr_header,
                        "tooltip": curr_tooltip,
                    })
                pending_serialize = False
                curr_tooltip = None

        return fields

    def _parse_equipment_category_rule(self, class_body: str) -> Optional[Dict[str, Any]]:
        m = re.search(r"public\s+EquipmentCategory\s+Category\s*\{\s*get\s*\{\s*return\s+([^;]+);\s*\}\s*\}", class_body)
        if not m:
            return None
        expr = m.group(1).strip()
        # 예: _part == ArmorPart.Head ? EquipmentCategory.Head : EquipmentCategory.Body
        m_tern = re.match(
            r"(_\w+)\s*==\s*(\w+)\.(\w+)\s*\?\s*EquipmentCategory\.(\w+)\s*:\s*EquipmentCategory\.(\w+)",
            expr,
        )
        if m_tern:
            return {
                "kind": "conditional",
                "field": field_to_camel(m_tern.group(1)),
                "enumType": m_tern.group(2),
                "equalsMember": m_tern.group(3),
                "trueCategory": m_tern.group(4),
                "falseCategory": m_tern.group(5),
            }
        m_const = re.match(r"EquipmentCategory\.(\w+)", expr)
        if m_const:
            return {
                "kind": "constant",
                "category": m_const.group(1),
            }
        return None

    def _parse_type_name_rules(self, text: str) -> None:
        m_method = re.search(
            r"public\s+static\s+string\s+GetTypeName\s*\(\s*ItemData\s+\w+\s*\)\s*\{([^}]+)\}",
            text,
        )
        if not m_method:
            return
        body = m_method.group(1)

        # if (itemData is ClassName [varName]) return ...;
        pattern = re.compile(
            r"if\s*\(\s*\w+\s+is\s+(?P<cls>\w+)(?:\s+(?P<var>\w+))?\s*\)\s*"
            r"return\s+(?P<ret>[^;]+);",
            re.MULTILINE,
        )
        for m in pattern.finditer(body):
            cls_name = m.group("cls")
            ret_expr = m.group("ret").strip()
            # 단순 문자열 반환: "무기"
            m_str = re.fullmatch(r'"([^"]+)"', ret_expr)
            if m_str:
                self.type_name_rules.append({
                    "className": cls_name,
                    "kind": "constant",
                    "labelKo": m_str.group(1),
                })
                continue

            # 삼항 연산자 패턴 1: armorType.Part == ArmorPart.Head ? "투구" : "갑옷"
            m_tern_eq = re.search(
                r"\w+\.(\w+)\s*==\s*(\w+)\.(\w+)\s*\?\s*\"([^\"]+)\"\s*:\s*\"([^\"]+)\"",
                ret_expr,
            )
            if m_tern_eq:
                prop_name, enum_type, enum_member, label_true, label_false = m_tern_eq.groups()
                self.type_name_rules.append({
                    "className": cls_name,
                    "kind": "enum_equals",
                    "property": prop_name[0].lower() + prop_name[1:],
                    "enumType": enum_type,
                    "enumMember": enum_member,
                    "labelTrue": label_true,
                    "labelFalse": label_false,
                })
                continue

            # 삼항 연산자 패턴 2: consumableType.IsPotion ? "물약" : "음식"
            m_tern_is = re.search(
                r"\w+\.Is(\w+)\s*\?\s*\"([^\"]+)\"\s*:\s*\"([^\"]+)\"",
                ret_expr,
            )
            if m_tern_is:
                target_member, label_true, label_false = m_tern_is.groups()
                self.type_name_rules.append({
                    "className": cls_name,
                    "kind": "is_member",
                    "targetMember": target_member,
                    "labelTrue": label_true,
                    "labelFalse": label_false,
                })

        # 기본 fallback return 추출
        all_returns = re.findall(r'^\s*return\s+"([^"]+)";', body, re.MULTILINE)
        if all_returns:
            self.default_type_name_ko = all_returns[-1]

    def eval_csharp_default(self, cs_type: str, expr: str) -> Any:
        if cs_type == "int":
            if expr and re.fullmatch(r"-?\d+", expr):
                return int(expr)
            return 0
        if cs_type == "float":
            clean = expr.rstrip("fF").strip()
            if clean and re.fullmatch(r"-?(?:\d+\.\d*|\.\d+|\d+)", clean):
                return float(clean)
            return 0.0
        if cs_type == "bool":
            return expr.strip().lower() == "true"
        if cs_type == "string":
            if expr.startswith('"') and expr.endswith('"'):
                return expr[1:-1]
            return ""
        if cs_type == "Vector2Int":
            if "Vector2Int.one" in expr:
                return {"x": 1, "y": 1}
            m = re.search(r"Vector2Int\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)", expr)
            if m:
                return {"x": int(m.group(1)), "y": int(m.group(2))}
            return {"x": 0, "y": 0}
        if cs_type == "Vector3":
            if "Vector3.one" in expr:
                return {"x": 1.0, "y": 1.0, "z": 1.0}
            m = re.search(
                r"Vector3\(\s*([0-9.-]+)[fF]?\s*,\s*([0-9.-]+)[fF]?\s*,\s*([0-9.-]+)[fF]?\s*\)",
                expr,
            )
            if m:
                return {"x": float(m.group(1)), "y": float(m.group(2)), "z": float(m.group(3))}
            return {"x": 0.0, "y": 0.0, "z": 0.0}
        if cs_type in self.enums:
            enum_map = self.enums[cs_type]
            if "." in expr:
                member = expr.split(".")[-1].strip()
                return member
            return enum_map.get(0, next(iter(enum_map.values()), None))
        return None

    def get_enum_member_name(self, enum_type: str, raw_val: Any) -> str:
        enum_map = self.enums.get(enum_type, {})
        if isinstance(raw_val, int):
            return enum_map.get(raw_val, str(raw_val))
        if isinstance(raw_val, str):
            return raw_val
        return enum_map.get(0, "")

    def get_enum_label_ko(self, enum_type: str, member_name: str) -> Optional[str]:
        if enum_type in self.enum_switch_labels and member_name in self.enum_switch_labels[enum_type]:
            return self.enum_switch_labels[enum_type][member_name]
        if enum_type in self.enum_member_comments and member_name in self.enum_member_comments[enum_type]:
            return self.enum_member_comments[enum_type][member_name]
        return None


# ============================================================================
# 3. Unity .meta 및 Sprite Sheet 인덱서
# ============================================================================

class UnityAssetIndex:
    def __init__(self, assets_dir: str) -> None:
        self.assets_dir = os.path.abspath(assets_dir)
        self.project_root = os.path.dirname(self.assets_dir)
        self.guid_to_relpath: Dict[str, str] = {}
        self.guid_to_abspath: Dict[str, str] = {}
        self._texture_meta_cache: Dict[str, Dict[str, Any]] = {}

    def build_guid_index(self, priority_subdirs: Optional[List[str]] = None) -> None:
        search_roots: List[str] = []
        if priority_subdirs:
            for sub in priority_subdirs:
                candidate = os.path.join(self.assets_dir, sub)
                if os.path.isdir(candidate):
                    search_roots.append(candidate)
        if not search_roots:
            search_roots = [self.assets_dir]

        for root_dir in search_roots:
            for dirpath, _, filenames in os.walk(root_dir):
                for fname in filenames:
                    if not fname.endswith(".meta"):
                        continue
                    meta_path = os.path.join(dirpath, fname)
                    guid = self._extract_guid_fast(meta_path)
                    if guid:
                        asset_abspath = meta_path[:-5]
                        rel_path = os.path.relpath(asset_abspath, self.project_root).replace("\\", "/")
                        self.guid_to_relpath[guid] = rel_path
                        self.guid_to_abspath[guid] = asset_abspath

    @staticmethod
    def _extract_guid_fast(meta_path: str) -> Optional[str]:
        try:
            with open(meta_path, "r", encoding="utf-8", errors="ignore") as fp:
                head = fp.read(256)
            m = re.search(r"^guid:\s*([0-9a-fA-F]+)", head, re.MULTILINE)
            return m.group(1) if m else None
        except OSError:
            return None

    def get_texture_sprite_info(self, guid: str, file_id: int) -> Optional[Dict[str, Any]]:
        if not guid or file_id == 0:
            return None

        rel_path = self.guid_to_relpath.get(guid)
        abs_path = self.guid_to_abspath.get(guid)
        if not rel_path or not abs_path:
            return {
                "guid": guid,
                "fileId": file_id,
                "spriteId": None,
                "texturePath": None,
                "spriteName": None,
                "spriteMode": "Unknown",
                "pixelsPerUnit": None,
                "rect": None,
                "pivot": None,
                "iconKey": f"icons/{guid}_{file_id}.png",
            }

        tex_meta = self._get_parsed_texture_meta(guid, abs_path + ".meta")
        sprite_mode_int = tex_meta.get("spriteMode", 1)
        sprite_mode = "Multiple" if sprite_mode_int == 2 else "Single"
        ppu = tex_meta.get("spritePixelsToUnits", 100)
        sprites_by_id: Dict[int, Dict[str, Any]] = tex_meta.get("sprites_by_id", {})
        name_table: Dict[int, str] = tex_meta.get("name_table", {})

        base_name = os.path.splitext(os.path.basename(rel_path))[0]

        if file_id in sprites_by_id:
            sp = sprites_by_id[file_id]
            sprite_name = sp["name"]
            return {
                "guid": guid,
                "fileId": file_id,
                "spriteId": sp.get("spriteID"),
                "texturePath": rel_path,
                "spriteName": sprite_name,
                "spriteMode": sprite_mode,
                "pixelsPerUnit": ppu,
                "rect": sp.get("rect"),
                "pivot": sp.get("pivot"),
                "iconKey": f"icons/{sprite_name}.png",
            }

        sprite_name = name_table.get(file_id, base_name)
        return {
            "guid": guid,
            "fileId": file_id,
            "spriteId": tex_meta.get("singleSpriteID"),
            "texturePath": rel_path,
            "spriteName": sprite_name,
            "spriteMode": sprite_mode,
            "pixelsPerUnit": ppu,
            "rect": None,
            "pivot": tex_meta.get("spritePivot", {"x": 0.5, "y": 0.5}),
            "iconKey": f"icons/{sprite_name}.png",
        }

    def _get_parsed_texture_meta(self, guid: str, meta_path: str) -> Dict[str, Any]:
        if guid in self._texture_meta_cache:
            return self._texture_meta_cache[guid]

        info: Dict[str, Any] = {
            "spriteMode": 1,
            "spritePixelsToUnits": 100,
            "spritePivot": {"x": 0.5, "y": 0.5},
            "singleSpriteID": None,
            "sprites_by_id": {},
            "name_table": {},
        }

        if not os.path.isfile(meta_path):
            self._texture_meta_cache[guid] = info
            return info

        with open(meta_path, "r", encoding="utf-8", errors="ignore") as fp:
            text = fp.read()

        m_mode = re.search(r"^\s*spriteMode:\s*(\d+)", text, re.MULTILINE)
        if m_mode:
            info["spriteMode"] = int(m_mode.group(1))

        m_ppu = re.search(r"^\s*spritePixelsToUnits:\s*([0-9.]+)", text, re.MULTILINE)
        if m_ppu:
            val = float(m_ppu.group(1))
            info["spritePixelsToUnits"] = int(val) if val.is_integer() else val

        m_pivot = re.search(r"^\s*spritePivot:\s*(\{[^}]+\})", text, re.MULTILINE)
        if m_pivot:
            info["spritePivot"] = parse_inline_dict(m_pivot.group(1))

        m_single_id = re.search(r"^\s*spriteID:\s*([0-9a-fA-F]+)", text, re.MULTILINE)
        if m_single_id:
            info["singleSpriteID"] = m_single_id.group(1)

        sprite_pattern = re.compile(
            r"-\s*serializedVersion:\s*\d+\s*\r?\n"
            r"\s*name:\s*(?P<name>[^\r\n]+)\r?\n"
            r"\s*rect:\s*\r?\n"
            r"\s*serializedVersion:\s*\d+\s*\r?\n"
            r"\s*x:\s*(?P<x>[0-9.-]+)\r?\n"
            r"\s*y:\s*(?P<y>[0-9.-]+)\r?\n"
            r"\s*width:\s*(?P<w>[0-9.-]+)\r?\n"
            r"\s*height:\s*(?P<h>[0-9.-]+)\r?\n"
            r"\s*alignment:\s*(?P<align>-?\d+)\r?\n"
            r"\s*pivot:\s*(?P<pivot>\{[^}]+\})"
            r".*?"
            r"\s*spriteID:\s*(?P<spriteID>[0-9a-fA-F]+)\r?\n"
            r"\s*internalID:\s*(?P<internalID>-?\d+)",
            re.DOTALL,
        )

        sprites_by_id: Dict[int, Dict[str, Any]] = {}
        for m in sprite_pattern.finditer(text):
            internal_id = int(m.group("internalID"))
            x_val = float(m.group("x"))
            y_val = float(m.group("y"))
            w_val = float(m.group("w"))
            h_val = float(m.group("h"))
            sprites_by_id[internal_id] = {
                "name": m.group("name").strip(),
                "spriteID": m.group("spriteID").strip(),
                "internalID": internal_id,
                "rect": {
                    "x": int(x_val) if x_val.is_integer() else x_val,
                    "y": int(y_val) if y_val.is_integer() else y_val,
                    "width": int(w_val) if w_val.is_integer() else w_val,
                    "height": int(h_val) if h_val.is_integer() else h_val,
                },
                "pivot": parse_inline_dict(m.group("pivot")),
            }

        info["sprites_by_id"] = sprites_by_id

        m_table = re.search(r"nameFileIdTable:\s*\r?\n((?:\s+[^\r\n]+:\s*-?\d+\r?\n)+)", text)
        if m_table:
            for line in m_table.group(1).splitlines():
                if ":" in line:
                    k, v = line.strip().split(":", 1)
                    try:
                        info["name_table"][int(v.strip())] = k.strip()
                    except ValueError:
                        pass

        self._texture_meta_cache[guid] = info
        return info


# ============================================================================
# 4. 동적 대분류(Category) 및 속성(Attributes) 추출 엔진
# ============================================================================

def resolve_script_class(raw: Dict[str, Any], discoverer: CSharpSchemaDiscoverer) -> str:
    """YAML의 m_EditorClassIdentifier 또는 m_Script.guid로부터 동적으로 클래스명을 식별합니다."""
    editor_id = str(raw.get("m_EditorClassIdentifier", "") or "")
    if "::" in editor_id:
        cls_name = editor_id.split("::")[-1].strip()
        if cls_name:
            return cls_name
    script_ref = raw.get("m_Script")
    if isinstance(script_ref, dict):
        guid = str(script_ref.get("guid", ""))
        if guid in discoverer.guid_to_class:
            return discoverer.guid_to_class[guid]
    return discoverer.base_class


def derive_dynamic_category(
    script_class: str,
    attributes: Dict[str, Any],
    asset_name: str,
    discoverer: CSharpSchemaDiscoverer,
) -> Tuple[str, str]:
    """
    하드코딩된 대분류 목록에 의존하지 않고,
    1) C# ItemUIFormatter.GetTypeName()에서 동적 추출한 규칙
    2) 클래스명 접미사(ItemData 제거) 및 에셋 접두사(<ID>_<Prefix>_<Name>)
    로부터 영문 대분류(itemType)와 한글 표시명(itemTypeKo)을 동적으로 결정합니다.
    """
    # 1. 영문 대분류(itemType) 동적 도출
    if script_class == discoverer.base_class:
        item_type = "Material"
    else:
        # 예: WeaponItemData -> Weapon, FishingRodItemData -> FishingRod
        stripped = re.sub(r"(?:ItemData|Data)$", "", script_class)
        item_type = stripped if stripped else script_class

    # 2. ItemUIFormatter.GetTypeName() 동적 규칙 평가
    item_type_ko: Optional[str] = None
    for rule in discoverer.type_name_rules:
        if rule["className"] != script_class:
            continue
        if rule["kind"] == "constant":
            item_type_ko = rule["labelKo"]
            break
        elif rule["kind"] == "enum_equals":
            prop_val = attributes.get(rule["property"])
            is_match = prop_val == rule["enumMember"]
            item_type_ko = rule["labelTrue"] if is_match else rule["labelFalse"]
            if isinstance(prop_val, str) and prop_val:
                item_type = prop_val
            break
        elif rule["kind"] == "is_member":
            target_member = rule["targetMember"]
            # attributes 내 enum 값 중 target_member와 일치하는 필드가 있는지 확인
            matched_val = None
            for k, v in attributes.items():
                if isinstance(v, str) and (v == target_member or k == "kind"):
                    matched_val = v
                    if v == target_member:
                        break
            is_match = matched_val == target_member
            item_type_ko = rule["labelTrue"] if is_match else rule["labelFalse"]
            if isinstance(matched_val, str) and matched_val:
                item_type = matched_val
            break

    if not item_type_ko:
        if script_class == discoverer.base_class:
            item_type_ko = discoverer.default_type_name_ko
        else:
            # ItemUIFormatter.cs에 아직 등록되지 않은 신규 클래스일 경우 menuName 또는 클래스명 사용
            cinfo = discoverer.item_classes.get(script_class, {})
            menu_name = cinfo.get("menuName")
            if menu_name:
                item_type_ko = menu_name.split("/")[-1].replace("Item Data", "").replace("Data", "").strip()
            if not item_type_ko:
                item_type_ko = item_type

    return item_type, item_type_ko


def resolve_equipment_category(
    script_class: str,
    attributes: Dict[str, Any],
    discoverer: CSharpSchemaDiscoverer,
) -> Tuple[Optional[str], Optional[str]]:
    cinfo = discoverer.item_classes.get(script_class)
    if not cinfo:
        return None, None
    rule = cinfo.get("equipmentCategoryRule")
    if not rule:
        return None, None

    cat_en: Optional[str] = None
    if rule["kind"] == "constant":
        cat_en = rule["category"]
    elif rule["kind"] == "conditional":
        fval = attributes.get(rule["field"])
        cat_en = rule["trueCategory"] if fval == rule["equalsMember"] else rule["falseCategory"]

    if not cat_en:
        return None, None

    slot_labels = discoverer.enum_switch_labels.get("EquipmentSlotType", {})
    cat_ko = slot_labels.get(cat_en)
    if not cat_ko:
        if cat_en.startswith("Accessory"):
            cat_ko = slot_labels.get("Accessory3", "장신구")
        elif cat_en == "Weapon":
            cat_ko = "무기"
        else:
            cat_ko = cat_en
    return cat_en, cat_ko


def build_dynamic_stats_summary(attributes: Dict[str, Any]) -> str:
    """
    아이템의 attributes로부터 인게임 툴팁(ItemUIFormatter.GetStats) 호환 요약 텍스트를 생성합니다.
    신규 대분류 아이템이 추가된 경우에도 주요 수치형/불리언/크기 속성을 자동으로 요약합니다.
    """
    # 1. 무기형 (damage + range + cooldown + attackShape)
    if "damage" in attributes and "range" in attributes and "cooldown" in attributes:
        shape_ko = attributes.get("attackShapeKo") or attributes.get("attackShape", "")
        lines = [
            f"공격력  {attributes['damage']}",
            f"사거리  {fmt_fixed(float(attributes['range']), 1)}",
            f"공격 간격  {fmt_fixed(float(attributes['cooldown']), 2)}초",
            f"공격 형태  {shape_ko}",
        ]
        cd_mult = float(attributes.get("cooldownMoveSpeedMultiplier", 1.0))
        if cd_mult < 0.999:
            penalty = round_to_int((1.0 - cd_mult) * 100.0)
            lines.append(f"쿨타임 이동 속도  -{penalty}%")
        dash = float(attributes.get("dashDistance", 0.0))
        if dash > 0.001:
            lines.append(f"돌진 거리  {fmt_fixed(dash, 1)}")
        return "\n".join(lines)

    # 2. 원거리/활형 (damage + arrowRange + fireCooldown)
    if "damage" in attributes and "arrowRange" in attributes and "fireCooldown" in attributes:
        return (
            f"공격력  {attributes['damage']}\n"
            f"사거리  {fmt_fixed(float(attributes['arrowRange']), 1)} "
            f"(조준 {fmt_fixed(float(attributes.get('aimAngle', 0.0)), 0)}°)\n"
            f"발사 간격  {fmt_fixed(float(attributes['fireCooldown']), 2)}초"
        )

    # 3. 방패형 (guardRadius + damageReductionRatio)
    if "guardRadius" in attributes and "damageReductionRatio" in attributes:
        red_pct = round_to_int(float(attributes["damageReductionRatio"]) * 100.0)
        spd_pct = round_to_int((1.0 - float(attributes.get("moveSpeedMultiplier", 1.0))) * 100.0)
        return (
            f"방어 범위  {fmt_fixed(float(attributes['guardRadius']), 1)} "
            f"({fmt_fixed(float(attributes.get('guardAngle', 0.0)), 0)}°)\n"
            f"피해 감소  {red_pct}%\n"
            f"이동 속도  -{spd_pct}%\n"
            "보조 도구 칸에 장착 (우클릭)"
        )

    # 4. 방어구형 (defense + part)
    if "defense" in attributes and "part" in attributes:
        lines = [f"방어력  {attributes['defense']}"]
        if int(attributes.get("maxHealthBonus", 0)) > 0:
            lines.append(f"최대 체력  +{attributes['maxHealthBonus']}")
        slot_ko = "투구" if attributes["part"] == "Head" else "갑옷"
        lines.append(f"{slot_ko} 칸에 장착 (우클릭)")
        return "\n".join(lines)

    # 5. 장신구형 (attackBonus / moveSpeedBonus)
    if "attackBonus" in attributes or "moveSpeedBonus" in attributes:
        lines = []
        if int(attributes.get("attackBonus", 0)) > 0:
            lines.append(f"공격력  +{attributes['attackBonus']}")
        if float(attributes.get("moveSpeedBonus", 0.0)) > 0.0001:
            lines.append(f"이동 속도  +{round_to_int(float(attributes['moveSpeedBonus']) * 100.0)}%")
        lines.append("장신구 칸에 장착 (우클릭)")
        return "\n".join(lines)

    # 6. 소모품형 (kind + size + duration)
    if "size" in attributes and "duration" in attributes:
        is_potion = attributes.get("kind") == "Potion"
        gauge = "조제" if is_potion else "위장"
        lines = [f"{gauge} {attributes['size']}칸 · {format_duration_ko(float(attributes['duration']))}"]
        if int(attributes.get("instantHeal", 0)) > 0:
            lines.append(f"즉시 회복  +{attributes['instantHeal']}")
        if attributes.get("curesAilments"):
            lines.append("중독·냉기 해제")
        if int(attributes.get("maxHealthBonus", 0)) > 0:
            lines.append(f"최대 HP  +{attributes['maxHealthBonus']}")
        if int(attributes.get("maxManaBonus", 0)) > 0:
            lines.append(f"최대 MP  +{attributes['maxManaBonus']}")
        regen = float(attributes.get("healthRegenPerSecond", 0.0))
        if regen > 0.0:
            regen_str = f"{int(regen)}" if regen.is_integer() else f"{regen:.1f}"
            lines.append(f"체력 재생  +{regen_str}/초")
        effect_ko = attributes.get("effectKo")
        if effect_ko:
            lines.append(str(effect_ko))
        lines.append("물약 칸에 넣고 Q·E로 마시기" if is_potion else "퀵슬롯에서 우클릭으로 먹기")
        return "\n".join(lines)

    # 7. 건축/설치형 (placeSize)
    if "placeSize" in attributes and isinstance(attributes["placeSize"], dict):
        ps = attributes["placeSize"]
        return f"설치 크기  {ps.get('x', 1)} x {ps.get('y', 1)}"

    # 8. 향후 추가될 임의의 신규 아이템 클래스용 범용 폴백 요약
    summary_parts: List[str] = []
    for k, v in attributes.items():
        if k.endswith("Ko") or isinstance(v, (dict, list)) or v is None or v is False:
            continue
        summary_parts.append(f"{k}: {v}")
    return "\n".join(summary_parts[:5])


# ============================================================================
# 5. 전체 아이템 에셋 파싱 및 동적 스키마 메타데이터 조립
# ============================================================================

def extract_all_items(
    index: UnityAssetIndex,
    discoverer: CSharpSchemaDiscoverer,
    items_dir: str,
    recipes_dir: Optional[str] = None,
) -> Dict[str, Any]:
    asset_files = sorted(glob.glob(os.path.join(items_dir, "**", "*.asset"), recursive=True))

    # 1차 패스: 모든 아이템의 기본 메타데이터 수집 (교차 참조 해결용)
    raw_items: List[Tuple[str, Optional[str], Dict[str, Any]]] = []
    guid_to_basic_item: Dict[str, Dict[str, Any]] = {}

    for fpath in asset_files:
        raw = parse_unity_monobehaviour_yaml(fpath)
        if "_itemId" not in raw:
            continue
        asset_guid = index._extract_guid_fast(fpath + ".meta")
        raw_items.append((fpath, asset_guid, raw))
        if asset_guid:
            guid_to_basic_item[asset_guid] = {
                "itemId": int(raw.get("_itemId", 0)),
                "displayName": str(raw.get("_displayName", "") or ""),
                "assetName": str(raw.get("m_Name", os.path.splitext(os.path.basename(fpath))[0])),
                "guid": asset_guid,
            }

    # 외부 ScriptableObject 참조(예: NPCData, 진화 무기 등) 범용 리졸버
    so_ref_cache: Dict[str, Dict[str, Any]] = {}

    def resolve_so_reference(ref_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        guid = str(ref_dict.get("guid", "") or "")
        file_id = int(ref_dict.get("fileID", 0) or 0)
        if not guid or file_id == 0:
            return None
        if guid in guid_to_basic_item:
            return guid_to_basic_item[guid]
        if guid in so_ref_cache:
            return so_ref_cache[guid]

        target_abs = index.guid_to_abspath.get(guid)
        target_rel = index.guid_to_relpath.get(guid)
        if target_abs and os.path.isfile(target_abs) and target_abs.endswith(".asset"):
            t_raw = parse_unity_monobehaviour_yaml(target_abs)
            resolved: Dict[str, Any] = {
                "assetName": str(t_raw.get("m_Name", os.path.splitext(os.path.basename(target_abs))[0])),
                "guid": guid,
                "assetPath": target_rel,
            }
            for id_key in ("_itemId", "_npcId", "_questId", "_recipeId", "_dialogueId"):
                if id_key in t_raw:
                    resolved[field_to_camel(id_key)] = t_raw[id_key]
            if "_displayName" in t_raw:
                resolved["displayName"] = t_raw["_displayName"]
            so_ref_cache[guid] = resolved
            return resolved

        return {"guid": guid, "fileId": file_id, "assetPath": target_rel}

    # 제작 레시피 역참조 인덱싱
    recipes_by_result: Dict[int, List[Dict[str, Any]]] = {}
    recipes_by_ingredient: Dict[int, List[Dict[str, Any]]] = {}
    item_id_to_name: Dict[int, str] = {
        int(r.get("_itemId", 0)): str(r.get("_displayName", "") or "")
        for _, _, r in raw_items
    }

    if recipes_dir and os.path.isdir(recipes_dir):
        for rf in sorted(glob.glob(os.path.join(recipes_dir, "**", "*.asset"), recursive=True)):
            r_raw = parse_unity_monobehaviour_yaml(rf)
            if "_recipeId" not in r_raw:
                continue
            recipe_id = int(r_raw.get("_recipeId", 0))
            recipe_name = str(r_raw.get("_recipeName", "") or "")
            station_int = int(r_raw.get("_stationType", 0))
            station_en = discoverer.get_enum_member_name("CraftingStationType", station_int)
            station_ko = discoverer.get_enum_label_ko("CraftingStationType", station_en) or station_en
            result_item_id = int(r_raw.get("_resultItemId", 0))
            result_amount = int(r_raw.get("_resultAmount", 1))
            ing_raw = r_raw.get("_ingredients") or []
            ingredients = []
            for ing in ing_raw:
                if isinstance(ing, dict):
                    ing_id = int(ing.get("_itemId", 0))
                    ing_amt = int(ing.get("_amount", 1))
                    ingredients.append({
                        "itemId": ing_id,
                        "displayName": item_id_to_name.get(ing_id, f"Item {ing_id}"),
                        "amount": ing_amt,
                    })

            recipe_entry = {
                "recipeId": recipe_id,
                "recipeName": recipe_name,
                "stationType": station_en,
                "stationTypeKo": station_ko,
                "resultItemId": result_item_id,
                "resultDisplayName": item_id_to_name.get(result_item_id, f"Item {result_item_id}"),
                "resultAmount": result_amount,
                "ingredients": ingredients,
            }
            recipes_by_result.setdefault(result_item_id, []).append(recipe_entry)
            for ing in ingredients:
                recipes_by_ingredient.setdefault(ing["itemId"], []).append({
                    "recipeId": recipe_id,
                    "recipeName": recipe_name,
                    "stationType": station_en,
                    "stationTypeKo": station_ko,
                    "resultItemId": result_item_id,
                    "resultDisplayName": item_id_to_name.get(result_item_id, f"Item {result_item_id}"),
                    "resultAmount": result_amount,
                    "requiredAmount": ing["amount"],
                })

    # 2차 패스: 각 아이템 에셋의 동적 attributes 및 공통 필드 추출
    items: List[Dict[str, Any]] = []
    used_enums: Set[str] = set()

    for fpath, asset_guid, raw in raw_items:
        script_class = resolve_script_class(raw, discoverer)
        item_id = int(raw.get("_itemId", 0))
        asset_name = str(raw.get("m_Name", os.path.splitext(os.path.basename(fpath))[0]))
        rel_asset_path = os.path.relpath(fpath, index.project_root).replace("\\", "/")
        display_name = str(raw.get("_displayName", "") or "")
        description = str(raw.get("_description", "") or "")
        max_stack = int(raw.get("_maxStack", 99))

        # 에셋 파일명 컨벤션(<ID>_<Prefix>_<Name>)에서 접두사 추출
        m_prefix = re.match(r"^\d+_([A-Za-z0-9]+)_", asset_name)
        asset_prefix = m_prefix.group(1) if m_prefix else None

        icon_ref = raw.get("_icon") if isinstance(raw.get("_icon"), dict) else {}
        world_ref = raw.get("_worldSprite") if isinstance(raw.get("_worldSprite"), dict) else {}

        icon_info = index.get_texture_sprite_info(
            str(icon_ref.get("guid", "") or ""),
            int(icon_ref.get("fileID", 0) or 0),
        )
        world_sprite_info = index.get_texture_sprite_info(
            str(world_ref.get("guid", "") or ""),
            int(world_ref.get("fileID", 0) or 0),
        )

        # C# 클래스 정의에서 탐색된 필드 메타데이터 로드
        cinfo = discoverer.item_classes.get(script_class, {})
        c_fields: List[Dict[str, Any]] = [
            f for f in cinfo.get("fields", []) if f["rawName"] not in BASE_ITEM_FIELDS
        ]
        c_field_map: Dict[str, Dict[str, Any]] = {f["rawName"]: f for f in c_fields}

        attributes: Dict[str, Any] = {}

        # 1) C# 클래스에 선언된 직렬화 필드 추출 (YAML에 생략된 경우 C# 기본값 사용)
        for fmeta in c_fields:
            raw_key = fmeta["rawName"]
            prop_name = fmeta["name"]
            cs_type = fmeta["csharpType"]
            has_in_yaml = raw_key in raw
            yaml_val = raw.get(raw_key)

            if cs_type == "bool":
                val = bool(yaml_val) if has_in_yaml else bool(fmeta["defaultValue"])
                attributes[prop_name] = val
            elif cs_type == "int":
                val = int(yaml_val) if (has_in_yaml and yaml_val is not None) else int(fmeta["defaultValue"] or 0)
                attributes[prop_name] = val
            elif cs_type == "float":
                val = float(yaml_val) if (has_in_yaml and yaml_val is not None) else float(fmeta["defaultValue"] or 0.0)
                attributes[prop_name] = val
            elif cs_type == "string":
                val = str(yaml_val or "") if has_in_yaml else str(fmeta["defaultValue"] or "")
                attributes[prop_name] = val
            elif cs_type in ("Vector2Int", "Vector3"):
                if has_in_yaml and isinstance(yaml_val, dict):
                    attributes[prop_name] = yaml_val
                else:
                    attributes[prop_name] = fmeta["defaultValue"]
            elif cs_type in discoverer.enums:
                used_enums.add(cs_type)
                if has_in_yaml and yaml_val is not None:
                    member_name = discoverer.get_enum_member_name(cs_type, yaml_val)
                else:
                    member_name = str(fmeta["defaultValue"] or "")
                attributes[prop_name] = member_name
                ko_label = discoverer.get_enum_label_ko(cs_type, member_name)
                if ko_label is not None:
                    attributes[f"{prop_name}Ko"] = ko_label
            elif cs_type == "Sprite":
                if has_in_yaml and isinstance(yaml_val, dict):
                    attributes[prop_name] = index.get_texture_sprite_info(
                        str(yaml_val.get("guid", "") or ""),
                        int(yaml_val.get("fileID", 0) or 0),
                    )
                else:
                    attributes[prop_name] = None
            else:
                # 다른 ScriptableObject 참조(예: WeaponItemData, NPCData 등)
                if has_in_yaml and isinstance(yaml_val, dict):
                    attributes[prop_name] = resolve_so_reference(yaml_val)
                else:
                    attributes[prop_name] = None

        # 2) YAML에 존재하지만 C# 파서 목록에 없던 추가 커스텀 필드도 유실 없이 동적 추출
        for raw_key, yaml_val in raw.items():
            if not raw_key.startswith("_") or raw_key in BASE_ITEM_FIELDS or raw_key in c_field_map:
                continue
            prop_name = field_to_camel(raw_key)
            if isinstance(yaml_val, dict) and "fileID" in yaml_val:
                guid = str(yaml_val.get("guid", "") or "")
                fid = int(yaml_val.get("fileID", 0) or 0)
                rel = index.guid_to_relpath.get(guid, "")
                if rel.lower().endswith((".png", ".jpg", ".jpeg", ".tga", ".psd")):
                    attributes[prop_name] = index.get_texture_sprite_info(guid, fid)
                else:
                    attributes[prop_name] = resolve_so_reference(yaml_val)
            else:
                attributes[prop_name] = yaml_val

        # 동적 대분류(itemType, itemTypeKo) 및 장착 슬롯 결정
        item_type, item_type_ko = derive_dynamic_category(
            script_class=script_class,
            attributes=attributes,
            asset_name=asset_name,
            discoverer=discoverer,
        )
        equip_cat, equip_cat_ko = resolve_equipment_category(
            script_class=script_class,
            attributes=attributes,
            discoverer=discoverer,
        )
        stats_summary = build_dynamic_stats_summary(attributes)

        record: Dict[str, Any] = {
            "itemId": item_id,
            "assetName": asset_name,
            "assetGuid": asset_guid,
            "assetPath": rel_asset_path,
            "assetPrefix": asset_prefix,
            "scriptClass": script_class,
            "itemType": item_type,
            "itemTypeKo": item_type_ko,
            "equipmentCategory": equip_cat,
            "equipmentCategoryKo": equip_cat_ko,
            "displayName": display_name,
            "description": description,
            "maxStack": max_stack,
            "statsSummary": stats_summary,
            "icon": icon_info,
            "worldSprite": world_sprite_info,
            "attributes": attributes,
            "crafting": {
                "craftedBy": recipes_by_result.get(item_id, []),
                "usedIn": recipes_by_ingredient.get(item_id, []),
            },
        }
        items.append(record)

    items.sort(key=lambda x: x["itemId"])

    # 동적 카테고리 목록(categories) 자동 생성 (하드코딩 없이 실제 추출된 데이터 + C# 클래스 기반)
    cat_map: Dict[str, Dict[str, Any]] = {}
    for it in items:
        itype = it["itemType"]
        if itype not in cat_map:
            cat_map[itype] = {
                "itemType": itype,
                "itemTypeKo": it["itemTypeKo"],
                "scriptClasses": [],
                "count": 0,
            }
        cat_entry = cat_map[itype]
        cat_entry["count"] += 1
        if it["scriptClass"] not in cat_entry["scriptClasses"]:
            cat_entry["scriptClasses"].append(it["scriptClass"])

    # 아직 에셋이 0개지만 C# 스크립트로 정의되어 있는 ItemData 파생 클래스도 스키마에 등록
    class_schemas: Dict[str, Any] = {}
    for cname, cinfo in sorted(discoverer.item_classes.items()):
        for f in cinfo.get("fields", []):
            if f["csharpType"] in discoverer.enums:
                used_enums.add(f["csharpType"])
        class_schemas[cname] = {
            "className": cname,
            "scriptGuid": cinfo.get("guid"),
            "scriptPath": os.path.relpath(cinfo["path"], index.project_root).replace("\\", "/"),
            "baseClasses": cinfo.get("bases", []),
            "menuName": cinfo.get("menuName"),
            "fields": [
                {
                    "name": f["name"],
                    "rawName": f["rawName"],
                    "csharpType": f["csharpType"],
                    "isEnum": f["csharpType"] in discoverer.enums,
                    "isBaseField": f["rawName"] in BASE_ITEM_FIELDS,
                    "defaultValue": f["defaultValue"],
                    "header": f["header"],
                    "tooltip": f["tooltip"],
                }
                for f in cinfo.get("fields", [])
            ],
        }

    enum_schemas: Dict[str, Any] = {}
    for ename in sorted(used_enums):
        emap = discoverer.enums.get(ename, {})
        enum_schemas[ename] = [
            {
                "value": val,
                "name": mname,
                "labelKo": discoverer.get_enum_label_ko(ename, mname),
            }
            for val, mname in sorted(emap.items(), key=lambda x: x[0])
        ]

    type_counts = {k: v["count"] for k, v in cat_map.items()}
    class_counts: Dict[str, int] = {}
    for it in items:
        sc = it["scriptClass"]
        class_counts[sc] = class_counts.get(sc, 0) + 1

    return {
        "schemaVersion": "1.1.0",
        "project": "DarkWood2 / ForestOfSteel",
        "sourcePath": os.path.relpath(items_dir, index.project_root).replace("\\", "/"),
        "totalCount": len(items),
        "categories": list(cat_map.values()),
        "summary": {
            "byItemType": type_counts,
            "byScriptClass": class_counts,
        },
        "classSchemas": class_schemas,
        "enumSchemas": enum_schemas,
        "items": items,
    }


# ============================================================================
# 6. 데이터 무결성 및 스키마 검증기
# ============================================================================

def validate_items_payload(payload: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    for root_req in ("schemaVersion", "categories", "classSchemas", "enumSchemas", "items"):
        if root_req not in payload:
            errors.append(f"최상위 '{root_req}' 필드가 누락되었습니다.")

    if "items" not in payload or not isinstance(payload["items"], list):
        return False, errors, warnings

    seen_ids: Dict[int, str] = {}
    required_keys = [
        "itemId",
        "assetName",
        "assetGuid",
        "assetPath",
        "scriptClass",
        "itemType",
        "itemTypeKo",
        "displayName",
        "description",
        "maxStack",
        "statsSummary",
        "icon",
        "worldSprite",
        "attributes",
    ]

    for idx, item in enumerate(payload["items"]):
        for req in required_keys:
            if req not in item:
                errors.append(f"items[{idx}] ({item.get('assetName', '?')}): 필수 필드 '{req}' 누락")

        item_id = item.get("itemId")
        asset_name = item.get("assetName", f"index_{idx}")
        if not isinstance(item_id, int) or item_id <= 0:
            errors.append(f"{asset_name}: 유효하지 않은 itemId ({item_id})")
        elif item_id in seen_ids:
            errors.append(f"중복된 itemId {item_id}: {seen_ids[item_id]} 및 {asset_name}")
        else:
            seen_ids[item_id] = asset_name

        if not item.get("displayName"):
            errors.append(f"[{item_id}] {asset_name}: displayName이 비어 있습니다.")

        if not isinstance(item.get("attributes"), dict):
            errors.append(f"[{item_id}] {asset_name}: attributes가 객체(dict)가 아닙니다.")

        icon = item.get("icon")
        if not icon or not isinstance(icon, dict):
            warnings.append(f"[{item_id}] {asset_name}: icon 참조가 비어 있습니다.")
        else:
            if not icon.get("texturePath"):
                errors.append(f"[{item_id}] {asset_name}: icon GUID({icon.get('guid')})에 해당하는 텍스처 경로를 찾을 수 없습니다.")
            if not icon.get("spriteName"):
                warnings.append(f"[{item_id}] {asset_name}: icon spriteName을 해석하지 못했습니다.")

    return len(errors) == 0, errors, warnings


# ============================================================================
# 7. CLI 엔트리포인트
# ============================================================================

def main() -> int:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_project_root = os.path.abspath(os.path.join(script_dir, "..", "DarkWood2", "ForestOfSteel"))
    default_output = os.path.join(script_dir, "items.json")

    parser = argparse.ArgumentParser(
        description="DarkWood2 (ForestOfSteel) 동적 유니티 아이템 데이터(.cs + .asset) -> JSON 추출 CLI"
    )
    parser.add_argument(
        "--project-root",
        default=default_project_root,
        help="Unity 프로젝트 루트 경로 (기본값: ../DarkWood2/ForestOfSteel)",
    )
    parser.add_argument(
        "--scripts-relpath",
        default="Assets/_Game/01.Scripts",
        help="프로젝트 루트 기준 C# 스크립트 폴더 상대 경로 (동적 클래스/Enum 탐색용)",
    )
    parser.add_argument(
        "--items-relpath",
        default="Assets/_Game/05.RuntimeData/Resources/Items",
        help="프로젝트 루트 기준 Items 에셋 폴더 상대 경로",
    )
    parser.add_argument(
        "--recipes-relpath",
        default="Assets/_Game/05.RuntimeData/Resources/Recipes",
        help="프로젝트 루트 기준 Recipes 에셋 폴더 상대 경로",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=default_output,
        help="출력 JSON 파일 경로 (기본값: ./items.json)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="들여쓰기 없는 압축(minified) JSON으로 출력",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="파일을 저장하지 않고 추출 및 스키마 무결성 검증만 수행",
    )
    args = parser.parse_args()

    project_root = os.path.abspath(args.project_root)
    assets_dir = os.path.join(project_root, "Assets")
    scripts_dir = os.path.join(project_root, args.scripts_relpath)
    items_dir = os.path.join(project_root, args.items_relpath)
    recipes_dir = os.path.join(project_root, args.recipes_relpath)

    if not os.path.isdir(assets_dir):
        print(f"[ERROR] Assets 폴더를 찾을 수 없습니다: {assets_dir}", file=sys.stderr)
        return 1
    if not os.path.isdir(items_dir):
        print(f"[ERROR] Items 폴더를 찾을 수 없습니다: {items_dir}", file=sys.stderr)
        return 1

    # 1. C# 스크립트에서 ItemData 파생 클래스, 직렬화 필드, Enum 정의 동적 탐색
    discoverer = CSharpSchemaDiscoverer(scripts_root=scripts_dir, base_class="ItemData")
    discoverer.discover()

    # 2. Unity .meta GUID 및 텍스처 스프라이트 시트 인덱싱
    index = UnityAssetIndex(assets_dir)
    index.build_guid_index(priority_subdirs=["_Game", "ForestReferenceAtlas"])

    # 3. 전체 아이템 추출 및 페이로드 조립
    payload = extract_all_items(
        index=index,
        discoverer=discoverer,
        items_dir=items_dir,
        recipes_dir=recipes_dir,
    )

    ok, errors, warnings = validate_items_payload(payload)
    for w in warnings:
        print(f"[WARN] {w}", file=sys.stderr)
    if not ok:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if not args.validate_only:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fp:
            if args.compact:
                json.dump(payload, fp, ensure_ascii=False, separators=(",", ":"))
            else:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.write("\n")

    print(
        f"[OK] 동적 클래스 {len(payload['classSchemas'])}종 / 카테고리 {len(payload['categories'])}종 / "
        f"아이템 {payload['totalCount']}종 추출 및 검증 완료 "
        f"(대분류별: {json.dumps(payload['summary']['byItemType'], ensure_ascii=False)}) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
