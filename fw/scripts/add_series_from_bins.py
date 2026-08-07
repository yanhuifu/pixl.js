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
"""
import os
import sys
import struct
import csv
import re
import argparse


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


def process_series(bins_dir, series_en, series_cn, data_dir, amiibo_rows, game_rows, link_rows,
                   existing_amiibo, linked_set, taken_ids):
    """把一个目录里的 bin 处理成一个系列。返回 (新增卡数, 新game_id或None)"""
    bins = []
    for root, _, files in os.walk(bins_dir):
        for f in files:
            if f.lower().endswith(".bin"):
                bins.append(os.path.join(root, f))
    if not bins:
        return 0, None

    cards = []
    for b in sorted(bins):
        amiibo_id = get_amiibo_id(b)
        if not amiibo_id:
            continue
        name_en = clean_name(os.path.basename(b))
        if amiibo_id in existing_amiibo:
            print(f"[SKIP] 数据库已存在: {amiibo_id}  {name_en}")
            continue
        cards.append((amiibo_id, name_en))
        existing_amiibo.add(amiibo_id)

    if not cards:
        return 0, None

    # 新建或复用系列
    game_id = None
    for r in game_rows:
        if len(r) >= 3 and r[2] == series_en:
            game_id = r[0]
            break
    if game_id is None:
        game_id = str(76)
        while game_id in taken_ids:
            game_id = str(int(game_id) + 1)
        taken_ids.add(game_id)
        game_rows.append([game_id, "0", series_en, series_cn or series_en, "500"])
        print(f"[NEW ] 新建系列文件夹: id={game_id}  {series_en} / {series_cn or series_en}")

    for amiibo_id, name_en in cards:
        amiibo_rows.append([amiibo_id, name_en, ""])
        print(f"[ADD ] {amiibo_id}  {name_en}")
        if (game_id, amiibo_id) not in linked_set:
            link_rows.append([game_id, amiibo_id, "", "", ""])
            linked_set.add((game_id, amiibo_id))

    return len(cards), game_id


def main():
    parser = argparse.ArgumentParser(description="一键把 bin 文件变成设备数据库里的新系列文件夹")
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

    amiibo_rows = load_rows(amiibo_csv)
    game_rows = load_rows(game_csv)
    link_rows = load_rows(link_csv)

    existing_amiibo = {r[0].lower() for r in amiibo_rows if len(r) >= 1 and len(r[0]) == 16}
    linked_set = {(r[0], r[1].lower()) for r in link_rows if len(r) >= 2}
    taken_ids = {r[0] for r in game_rows if len(r) >= 1 and r[0].isdigit()}

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
            n, _ = process_series(sub, entry, "", data_dir, amiibo_rows, game_rows, link_rows,
                                  existing_amiibo, linked_set, taken_ids)
            total_cards += n
    else:
        if not args.path or not args.series:
            print("[ERROR] 手动模式需要 path 和 --series 参数，或用 --auto 自动模式")
            sys.exit(1)
        print("\n处理系列: %s" % args.series)
        total_cards, _ = process_series(args.path, args.series, args.series_cn, data_dir,
                                        amiibo_rows, game_rows, link_rows,
                                        existing_amiibo, linked_set, taken_ids)

    write_rows(amiibo_csv, amiibo_rows)
    write_rows(game_csv, game_rows)
    write_rows(link_csv, link_rows)

    print("\n完成！数据库已更新，共新增 %d 张卡。" % total_cards)
    print("下一步：运行 fw/scripts/amiibo_db_gen.py 重新生成固件源码，然后编译。")


if __name__ == "__main__":
    main()
