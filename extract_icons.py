#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DarkWood2 (ForestOfSteel) 아이콘 추출 및 아틀라스 크롭 CLI (Milestone 4)
- items.json 에 기록된 icon, worldSprite 및 attributes 내 Sprite 참조들을 스캔합니다.
- Single 스프라이트는 원본 텍스처를 복사/최적화하고,
  Multiple(아틀라스) 스프라이트는 Unity 좌하단(bottom-left) 기준 rect 좌표를
  이미지 좌상단(top-left) 좌표로 변환해 개별 PNG 파일(icons/<spriteName>.png)로 추출합니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    print(
        "[ERROR] Pillow 라이브러리가 필요합니다. 'pip install Pillow' 실행 후 다시 시도해 주세요.",
        file=sys.stderr,
    )
    sys.exit(1)


def is_sprite_reference(obj: Any) -> bool:
    """객체가 extract_items.py가 생성한 SpriteReference 딕셔너리인지 판별합니다."""
    return (
        isinstance(obj, dict)
        and "iconKey" in obj
        and "texturePath" in obj
        and "spriteMode" in obj
        and bool(obj.get("iconKey"))
        and bool(obj.get("texturePath"))
    )


def collect_unique_sprites(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """items.json 전체에서 고유한 iconKey 별 SpriteReference 메타데이터를 수집합니다."""
    sprites: Dict[str, Dict[str, Any]] = {}

    for item in payload.get("items", []):
        for key in ("icon", "worldSprite"):
            ref = item.get(key)
            if is_sprite_reference(ref):
                sprites[ref["iconKey"]] = ref

        attrs = item.get("attributes")
        if isinstance(attrs, dict):
            for val in attrs.values():
                if is_sprite_reference(val):
                    sprites[val["iconKey"]] = val

    return sprites


def crop_unity_sprite(
    img: Image.Image,
    sprite_mode: str,
    rect: Optional[Dict[str, Any]],
) -> Image.Image:
    """
    Unity Texture2D/Sprite 좌표계(좌하단 원점)를 Pillow 좌표계(좌상단 원점)로 변환하여 크롭합니다.
    """
    if sprite_mode != "Multiple" or not isinstance(rect, dict):
        return img.copy()

    tex_w, tex_h = img.size
    x = float(rect.get("x", 0))
    y = float(rect.get("y", 0))
    w = float(rect.get("width", tex_w))
    h = float(rect.get("height", tex_h))

    left = max(0, min(tex_w, int(round(x))))
    right = max(left + 1, min(tex_w, int(round(x + w))))
    upper = max(0, min(tex_h, int(round(tex_h - (y + h)))))
    lower = max(upper + 1, min(tex_h, int(round(tex_h - y))))

    return img.crop((left, upper, right, lower))


def extract_all_icons(
    project_root: str,
    items_json_path: str,
    output_dir: str,
) -> Tuple[int, List[str]]:
    """
    items.json 내 모든 고유 스프라이트를 output_dir 아래에 개별 PNG 파일로 추출합니다.
    """
    if not os.path.isfile(items_json_path):
        raise FileNotFoundError(f"items.json 파일을 찾을 수 없습니다: {items_json_path}")

    with open(items_json_path, "r", encoding="utf-8") as fp:
        payload = json.load(fp)

    unique_sprites = collect_unique_sprites(payload)
    os.makedirs(output_dir, exist_ok=True)

    # 원본 아틀라스 텍스처 캐시 (동일 시트 반복 로드 방지)
    texture_cache: Dict[str, Image.Image] = {}
    extracted_count = 0
    errors: List[str] = []

    try:
        for icon_key in sorted(unique_sprites.keys()):
            ref = unique_sprites[icon_key]
            tex_rel = ref.get("texturePath")
            if not tex_rel:
                errors.append(f"{icon_key}: texturePath가 비어 있습니다.")
                continue

            tex_abs = os.path.join(project_root, tex_rel.replace("/", os.sep))
            if not os.path.isfile(tex_abs):
                errors.append(f"{icon_key}: 원본 텍스처 파일을 찾을 수 없습니다 ({tex_abs})")
                continue

            if tex_abs not in texture_cache:
                src_img = Image.open(tex_abs)
                src_img.load()
                if src_img.mode not in ("RGBA", "RGB"):
                    src_img = src_img.convert("RGBA")
                texture_cache[tex_abs] = src_img

            base_img = texture_cache[tex_abs]
            cropped = crop_unity_sprite(
                img=base_img,
                sprite_mode=ref.get("spriteMode", "Single"),
                rect=ref.get("rect"),
            )

            # iconKey 가 "icons/Workbench.png" 형태이므로 파일명만 추출하여 output_dir 에 저장
            filename = os.path.basename(icon_key)
            out_path = os.path.join(output_dir, filename)
            cropped.save(out_path, format="PNG", optimize=True)
            extracted_count += 1
    finally:
        for cached_img in texture_cache.values():
            cached_img.close()

    return extracted_count, errors


def main() -> int:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_project_root = os.path.abspath(os.path.join(script_dir, "..", "DarkWood2", "ForestOfSteel"))
    default_items_json = os.path.join(script_dir, "items.json")
    default_output_dir = os.path.join(script_dir, "icons")

    parser = argparse.ArgumentParser(
        description="DarkWood2 (ForestOfSteel) 아이템 아이콘 PNG 추출 및 아틀라스 크롭 CLI"
    )
    parser.add_argument(
        "--project-root",
        default=default_project_root,
        help="Unity 프로젝트 루트 경로 (기본값: ../DarkWood2/ForestOfSteel)",
    )
    parser.add_argument(
        "--items-json",
        default=default_items_json,
        help="입력 items.json 파일 경로 (기본값: ./items.json)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=default_output_dir,
        help="추출된 PNG 아이콘 저장 폴더 경로 (기본값: ./icons)",
    )
    args = parser.parse_args()

    try:
        count, errors = extract_all_icons(
            project_root=os.path.abspath(args.project_root),
            items_json_path=os.path.abspath(args.items_json),
            output_dir=os.path.abspath(args.output_dir),
        )
    except Exception as exc:
        print(f"[ERROR] 아이콘 추출 실패: {exc}", file=sys.stderr)
        return 1

    if errors:
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 2

    print(f"[OK] 고유 아이콘 스프라이트 {count}종 추출 완료 -> {os.path.abspath(args.output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
