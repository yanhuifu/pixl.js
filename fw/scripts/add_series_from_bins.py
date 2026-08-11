#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_series_from_bins.py —— 把 bin 文件变成设备数据库里的新"系列文件夹"

两种用法：

1) 自动扫描（GitHub Actions 云端用 / 本地一键用）：
   python add_series_from_bins.py --root <pixl.js根目录> --auto
   自动扫描 fw/data/Amiibo Bins/ 下的每一个子文件夹，
   每个子文件夹 = 一个系列（新文件夹），文件夹名 = 系列名。
   客户只需把 bin 传进 fw/data/Amiibo Bins/新系列名/ 即可。

2) 手动指定（可选）：
   python add_series_from_bins.py <bin目录> --series "英文名" --series-cn "中文名" --root <pixl.js根目录>

本工具只更新 3 个 CSV 数据库（amiidb_amiibo / amiidb_game / amiidb_link）。
之后运行 fw/scripts/amiibo_db_gen.py 重新生成固件源码。

【多语言修复 v2.0】（解决"切英文仍显示中文"的问题）
- 固件数据库只有"英文名 + 中文名"两列，除简体中文外的其它语言都显示英文名。
- 旧版本会把 bin 文件名（哪怕是中文）直接塞进"英文名"列、中文名留空，
  导致切英文时新加的卡还是显示中文。
- 本版本规则：
    1) bin 文件名含中文 → 自动作为"中文名"；英文名到同目录 en_names.csv 查表（按 amiibo ID）。
    2) bin 文件名是英文 → 直接作为"英文名"；中文名到 en_names.csv 查表（可选）。
    3) 系列文件夹名含中文 → 英文系列名到 en_names.csv 查表（type=series）。
    4) 查不到英文名 → 保留原显示并打印醒目警告，把英文名补进 en_names.csv 后重跑即可生效。
- 每次运行还会自动修复历史数据里"英文名列含中文"的错误行（自愈）。
"""
import os
import sys
import struct
import csv
import re
import argparse

CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def has_cjk(s):
    return bool(CJK_RE.search(s or ""))


def get_amiibo_id(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        print(f"[ERROR] 无法读取文件: {e}")
        return None
    if len(data) < 92:
        print(f"[ERROR] 文件过小，不是有效 Amiibo bin: {os.path.basename(path)}")
        return None
    head = struct.unpack(">I", data[84:88])[0]
    tail = struct.unpack(">I", data[88:92])[0]
    if head == 0 and tail == 0:
        print(f"[WARN] head/tail 全为 0，跳过: {os.path.basename(path)}")
        return None
    return ("%08x%08x" % (head, tail))


def clean_name(filename):
    name = filename
    if name.lower().endswith(".bin"):
        name = name[:-4]
    name = re.sub(r"[_ ]+[0-9a-fA-F]{8}[_ ]+[0-9a-fA-F]{8}(?:\s*\(\d+\))?", "", name)
    name = re.sub(r"[_ ]+[0-9a-fA-F]{16}(?:\s*\(\d+\))?", "", name)
    name = name.replace("_", " ")
    name = " ".join(name.split()).strip()
    return name or "Unknown"


def names_csv_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "en_names.csv")


def load_names_csv():
    """读取脚本同目录的 en_names.csv，返回 (amiibo_en, amiibo_cn, series_en, series_cn)"""
    amiibo_en, amiibo_cn = {}, {}
    series_en, series_cn = {}, {}
    path = names_csv_path()
    if not os.path.exists(path):
        print(f"[INFO] 未找到英文名映射表 {path}，中文文件名 bin 将按原名显示（可之后补建该文件）。")
        return amiibo_en, amiibo_cn, series_en, series_cn
    with open(path, "r", encoding="utf-8-sig") as f:
        for r in csv.reader(f):
            if not r or not r[0].strip() or r[0].strip().startswith("#"):
                continue
            if len(r) < 3:
                continue
            typ = r[0].strip().lower()
            key = r[1].strip()
            en = r[2].strip()
            cn = r[3].strip() if len(r) > 3 else ""
            if typ == "amiibo":
                if en:
                    amiibo_en[key.lower()] = en
                if cn:
                    amiibo_cn[key.lower()] = cn
            elif typ == "series":
                if en:
                    series_en[key] = en
                if cn:
                    series_cn[key] = cn
    return amiibo_en, amiibo_cn, series_en, series_cn


def resolve_bin_name(clean, amiibo_id, amiibo_en, amiibo_cn, missing):
    """根据文件名是否含中文 + 映射表，返回 (name_en, name_cn)"""
    if has_cjk(clean):
        name_cn = clean
        name_en = amiibo_en.get(amiibo_id.lower(), "")
        if not name_en:
            name_en = clean
            missing.append(("amiibo", amiibo_id))
        return name_en, name_cn
    else:
        name_en = clean
        name_cn = amiibo_cn.get(amiibo_id.lower(), "")
        return name_en, name_cn


def resolve_series_name(folder, explicit_en, explicit_cn, series_en, series_cn, missing):
    """返回 (game_en, game_cn)。manual 模式 explicit_en 不为 None。"""
    if explicit_en is not None:
        game_en = explicit_en.strip()
        game_cn = (explicit_cn or "").strip()
        if has_cjk(game_en):
            if not game_cn:
                game_cn = game_en
            mapped = series_en.get(game_en)
            if mapped:
                game_en = mapped
            else:
                missing.append(("series", game_en))
        return game_en, game_cn

    if has_cjk(folder):
        game_cn = folder
        game_en = series_en.get(folder, "")
        if not game_en:
            game_en = folder
            missing.append(("series", folder))
        return game_en, game_cn
    else:
        game_en = folder
        game_cn = series_cn.get(folder, "")
        return game_en, game_cn


def repair_existing_rows(amiibo_rows, game_rows, amiibo_en, amiibo_cn, series_en, series_cn):
    """自愈：把历史数据里"英文名列含中文"的行纠正为 (英文名, 中文名)。"""
    repaired = 0
    for r in amiibo_rows:
        if len(r) < 3:
            r.extend([""] * (3 - len(r)))
        if len(r[0]) != 16 or not has_cjk(r[1]):
            continue
        if not r[2]:
            r[2] = r[1]
        new_en = amiibo_en.get(r[0].lower(), "")
        if new_en:
            r[1] = new_en
            repaired += 1
            print(f"[REPAIR] amiibo {r[0]}: 英文名 -> {r[1]}，中文名 -> {r[2]}")
        else:
            print(f"[WARN] amiibo {r[0]} 英文名是中文且映射表里没有英文名，切英文仍显示 {r[1]}；"
                  f"请补进 en_names.csv（amiibo,{r[0]},英文名）")
    for r in game_rows:
        if len(r) < 4:
            r.extend([""] * (4 - len(r)))
        if not has_cjk(r[2]):
            continue
        if not r[3]:
            r[3] = r[2]
        new_en = series_en.get(r[2], "")
        if new_en:
            r[2] = new_en
            repaired += 1
            print(f"[REPAIR] series {r[3]}: 英文名 -> {r[2]}")
        else:
            print(f"[WARN] 系列 {r[3]} 的英文名是中文且映射表里没有英文名，切英文仍显示 {r[2]}；"
                  f"请补进 en_names.csv（series,{r[2]},英文名）")
    if repaired:
        print(f"[OK] 自动修复了 {repaired} 条历史数据。")
    return repaired


def load_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [r for r in csv.reader(f)]


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow(r)


def process_series(bins_dir, series_folder, explicit_en, explicit_cn, data_dir, amiibo_rows, game_rows,
                   link_rows, existing_amiibo, linked_set, taken_ids,
                   amiibo_en, amiibo_cn, series_en, series_cn, missing):
    """把一个目录里的 bin 处理成一个系列。返回 (新增卡数, 新game_id或None)"""
    bins = []
    for root, _, files in os.walk(bins_dir):
        for f in files:
            if f.lower().endswith(".bin"):
                bins.append(os.path.join(root, f))
    if not bins:
        return 0, None

    game_en, game_cn = resolve_series_name(series_folder, explicit_en, explicit_cn,
                                           series_en, series_cn, missing)

    cards = []
    for b in sorted(bins):
        amiibo_id = get_amiibo_id(b)
        if not amiibo_id:
            continue
        clean = clean_name(os.path.basename(b))
        if amiibo_id in existing_amiibo:
            print(f"[SKIP] 数据库已存在: {amiibo_id}  {clean}")
            continue
        name_en, name_cn = resolve_bin_name(clean, amiibo_id, amiibo_en, amiibo_cn, missing)
        cards.append((amiibo_id, name_en, name_cn))
        existing_amiibo.add(amiibo_id)

    if not cards:
        return 0, None

    # 新建或复用系列（按英文名或中文名匹配）
    game_id = None
    for r in game_rows:
        if len(r) >= 3 and r[2] == game_en:
            game_id = r[0]
            break
        if game_cn and len(r) >= 4 and r[3] == game_cn:
            game_id = r[0]
            break
    if game_id is None:
        game_id = str(76)
        while game_id in taken_ids:
            game_id = str(int(game_id) + 1)
        taken_ids.add(game_id)
        game_rows.append([game_id, "0", game_en, game_cn, "500"])
        print(f"[NEW ] 新建系列文件夹: id={game_id}  EN={game_en}  CN={game_cn or '-'}")

    for amiibo_id, name_en, name_cn in cards:
        amiibo_rows.append([amiibo_id, name_en, name_cn])
        print(f"[ADD ] {amiibo_id}  EN={name_en}  CN={name_cn or '-'}")
        if (game_id, amiibo_id) not in linked_set:
            link_rows.append([game_id, amiibo_id, "", "", ""])
            linked_set.add((game_id, amiibo_id))

    return len(cards), game_id


def main():
    parser = argparse.ArgumentParser(description="一键把 bin 文件变成设备数据库里的新系列文件夹（多语言版）")
    parser.add_argument("path", nargs="?", help="包含 .bin 的目录（手动模式用）")
    parser.add_argument("--root", required=True, help="pixl.js 源码根目录")
    parser.add_argument("--auto", action="store_true",
                        help="自动扫描 fw/data/Amiibo Bins/ 下每个子文件夹作为一个系列")
    parser.add_argument("--series", help="系列英文名（手动模式）")
    parser.add_argument("--series-cn", default="", help="系列中文名（手动模式）")
    args = parser.parse_args()

    data_dir = os.path.join(args.root, "fw", "data")
    amiibo_csv = os.path.join(data_dir, "amiidb_amiibo.csv")
    game_csv = os.path.join(data_dir, "amiidb_game.csv")
    link_csv = os.path.join(data_dir, "amiidb_link.csv")
    for f in (amiibo_csv, game_csv, link_csv):
        if not os.path.exists(f):
            print("[ERROR] 找不到数据库文件: %s" % f)
            sys.exit(1)

    amiibo_en, amiibo_cn, series_en, series_cn = load_names_csv()

    amiibo_rows = load_rows(amiibo_csv)
    game_rows = load_rows(game_csv)
    link_rows = load_rows(link_csv)

    # 自愈历史脏数据
    repair_existing_rows(amiibo_rows, game_rows, amiibo_en, amiibo_cn, series_en, series_cn)

    existing_amiibo = {r[0].lower() for r in amiibo_rows if len(r) >= 1 and len(r[0]) == 16}
    linked_set = {(r[0], r[1].lower()) for r in link_rows if len(r) >= 2}
    taken_ids = {r[0] for r in game_rows if len(r) >= 1 and r[0].isdigit()}

    missing = []
    total_cards = 0
    if args.auto:
        bins_root = os.path.join(data_dir, "Amiibo Bins")
        if not os.path.isdir(bins_root):
            print("[WARN] 还没有 Amiibo Bins 文件夹，本次不更新数据库。")
            return
        for entry in sorted(os.listdir(bins_root)):
            sub = os.path.join(bins_root, entry)
            if not os.path.isdir(sub):
                continue
            print("\n处理系列: %s" % entry)
            n, _ = process_series(sub, entry, None, None, data_dir, amiibo_rows, game_rows, link_rows,
                                  existing_amiibo, linked_set, taken_ids,
                                  amiibo_en, amiibo_cn, series_en, series_cn, missing)
            total_cards += n
    else:
        if not args.path or not args.series:
            print("[ERROR] 手动模式需要 path 和 --series 参数，或用 --auto 自动模式")
            sys.exit(1)
        print("\n处理系列: %s" % args.series)
        total_cards, _ = process_series(args.path, args.series, args.series, args.series_cn,
                                        data_dir, amiibo_rows, game_rows, link_rows,
                                        existing_amiibo, linked_set, taken_ids,
                                        amiibo_en, amiibo_cn, series_en, series_cn, missing)

    write_rows(amiibo_csv, amiibo_rows)
    write_rows(game_csv, game_rows)
    write_rows(link_csv, link_rows)

    print("\n完成！数据库已更新，共新增 %d 张卡。" % total_cards)

    if missing:
        print("\n[!] 以下内容没有找到英文名，切英文时仍会显示中文：")
        for typ, key in missing:
            if typ == "amiibo":
                print(f"    amiibo ID: {key}  ->  请把英文名写进 fw/scripts/en_names.csv 一行：amiibo,{key},英文名")
            else:
                print(f"    系列: {key}  ->  请把英文名写进 fw/scripts/en_names.csv 一行：series,{key},英文名")
        print("    补好后再重新运行本脚本即可自动生效。")

    print("下一步：运行 fw/scripts/amiibo_db_gen.py 重新生成固件源码，然后编译。")


if __name__ == "__main__":
    main()
